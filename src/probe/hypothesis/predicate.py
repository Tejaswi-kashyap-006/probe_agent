"""Predict a probe's outcome class from a set of rules.

Deterministic and free: no LLM call, which is what makes scoring every
candidate probe against every particle affordable.

Nothing here executes model-authored code. Rules arrive as validated data and
are interpreted by fixed Python, so a hypothesis is a value, not a program.
"""

from __future__ import annotations

from typing import Any

from probe.client import Probe, ProbeResult
from probe.hypothesis.rules import Rule, violation

# Structural failures are decided before value-level ones, matching how any
# sane request handler is written: shape first, then contents.
PRECEDENCE = (
    "mutual_exclusion",
    "required",
    "conditional_required",
    "type",
    "enum",
    "range",
    "format",
)

OK = "OK"
TRUNCATED = "TRUNCATED"


def _params_of(probe: Probe) -> dict[str, Any]:
    return dict(probe.body) if probe.body is not None else dict(probe.params)


def endpoint_of(probe: Probe, endpoints: tuple[str, ...]) -> str:
    for endpoint in endpoints:
        method, path = endpoint.split(" ", 1)
        if method != probe.method:
            continue
        if path == probe.path:
            return endpoint
        if "{id}" in path and probe.path.startswith(path.split("{id}")[0]):
            return endpoint
    return f"{probe.method} {probe.path}"


def predict(
    rules: list[Rule], probe: Probe, endpoints: tuple[str, ...]
) -> str:
    """The outcome class these rules imply for this probe."""
    endpoint = endpoint_of(probe, endpoints)
    params = _params_of(probe)
    relevant = [r for r in rules if r.endpoint == endpoint]

    for kind in PRECEDENCE:
        for rule in [r for r in relevant if r.kind == kind]:
            status = violation(rule, params)
            if status is not None:
                return str(status)

    cap_rule = next((r for r in relevant if r.kind == "pagination_cap"), None)
    if cap_rule is not None and cap_rule.cap is not None:
        asked = params.get(cap_rule.param)
        page = params.get("page")
        # Beyond the first page a short response could be the catalogue running
        # out rather than a cap, and the agent has no way to tell which. Only
        # the first page is predicted as truncation.
        first_page = page is None or page in (0, 1)
        if isinstance(asked, int) and not isinstance(asked, bool) and first_page:
            if asked > cap_rule.cap:
                return TRUNCATED
    return OK


def observed_class(result: ProbeResult) -> str:
    """The outcome class actually seen. Must agree with predict()'s vocabulary."""
    if result.status != 200:
        return str(result.status)

    asked = _params_of(result.probe).get("limit")
    page = _params_of(result.probe).get("page")
    count = result.body.get("count")
    first_page = page is None or page in (0, 1)
    if (
        isinstance(asked, int)
        and not isinstance(asked, bool)
        and isinstance(count, int)
        and first_page
        and count < asked
    ):
        return TRUNCATED
    return OK

