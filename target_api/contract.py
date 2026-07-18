"""Ground-truth contract: rule grammar, evaluator, and observable projection.

Agent code must never import this module. Rules are interpreted, never exec'd.
The evaluator is pure Python over native-typed params, so the same code serves
both the HTTP server and the offline identifiability check.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any

# Fixed catalogue size; makes GET /products item counts deterministic.
CATALOGUE_SIZE = 120

# Fixed seeded orders for GET /orders/{id}. Stateless: POST never adds to this.
SEEDED_ORDER_IDS = ("ORD-1001", "ORD-1002", "ORD-1003")


class PriorClass(str, Enum):
    """Whether a rule matches common API convention.

    counter_prior rules are ones an LLM cannot guess from endpoint names alone.
    Recall is always reported per-subset, never blended.
    """

    CONVENTIONAL = "conventional"
    COUNTER_PRIOR = "counter_prior"


class RuleKind(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    TYPE = "type"
    RANGE = "range"
    ENUM = "enum"
    FORMAT = "format"
    CONDITIONAL_REQUIRED = "conditional_required"
    MUTUAL_EXCLUSION = "mutual_exclusion"
    PAGINATION_CAP = "pagination_cap"
    RESOURCE_LOOKUP = "resource_lookup"


class Verbosity(str, Enum):
    """How much an error response leaks. Drives the observable projection."""

    VERBOSE = "verbose"  # status + error code + offending field names (easy)
    TERSE = "terse"  # status + error code, no field names (medium)
    BARE = "bare"  # status code only (hard)


class OutcomeClass(str, Enum):
    """The response class a hypothesis must predict."""

    OK = "OK"
    TRUNCATED = "TRUNCATED"
    ERR_400 = "400"
    ERR_404 = "404"
    ERR_409 = "409"
    ERR_422 = "422"


_STATUS_TO_CLASS = {
    200: OutcomeClass.OK,
    400: OutcomeClass.ERR_400,
    404: OutcomeClass.ERR_404,
    409: OutcomeClass.ERR_409,
    422: OutcomeClass.ERR_422,
}


@dataclass(frozen=True)
class Rule:
    """One atomic, independently checkable contract rule.

    Only the fields relevant to `kind` are populated. `status` encodes this
    rule's error semantics, so error-code choice is itself a recoverable fact.
    """

    id: str
    endpoint: str
    kind: RuleKind
    prior_class: PriorClass
    description: str
    param: str | None = None
    status: int = 400
    default: Any = None
    type_name: str | None = None
    lo: int | None = None
    hi: int | None = None
    values: tuple[str, ...] | None = None
    pattern: str | None = None
    example: str | None = None
    if_param: str | None = None
    if_value: Any = None
    then_param: str | None = None
    param_a: str | None = None
    param_b: str | None = None
    cap: int | None = None


def rule_as_dict(rule: Rule) -> dict[str, Any]:
    """Serialise a rule to the plain dicts the scorer consumes.

    The scorer must not import the ground truth, so it is handed data instead.
    """
    out = asdict(rule)
    out["kind"] = rule.kind.value
    out["prior_class"] = rule.prior_class.value
    if rule.values is not None:
        out["values"] = list(rule.values)
    return {k: v for k, v in out.items() if v is not None}


@dataclass(frozen=True)
class Contract:
    name: str
    verbosity: Verbosity
    rules: tuple[Rule, ...]
    endpoints: tuple[str, ...]

    def without(self, rule_id: str) -> Contract:
        """Contract with one rule removed. Used by the identifiability check."""
        return replace(self, rules=tuple(r for r in self.rules if r.id != rule_id))

    def replacing(self, rule_id: str, new_rule: Rule) -> Contract:
        """Contract with one rule swapped for a perturbed version of itself."""
        return replace(
            self, rules=tuple(new_rule if r.id == rule_id else r for r in self.rules)
        )

    def for_endpoint(self, endpoint: str) -> tuple[Rule, ...]:
        return tuple(r for r in self.rules if r.endpoint == endpoint)

    def params_of(self, endpoint: str) -> tuple[str, ...]:
        """Every param name mentioned by any rule on this endpoint."""
        names: list[str] = []
        for r in self.for_endpoint(endpoint):
            for n in (r.param, r.if_param, r.then_param, r.param_a, r.param_b):
                if n and n not in names:
                    names.append(n)
        return tuple(names)


@dataclass(frozen=True)
class Outcome:
    """Full internal result. `project()` is what the agent is allowed to see."""

    status: int
    outcome_class: OutcomeClass
    error_code: str | None
    fields: tuple[str, ...]
    body: dict[str, Any]

    def project(self, verbosity: Verbosity) -> dict[str, Any]:
        """Redact the outcome down to what this variant's errors actually leak.

        Body content is never redacted: it is data, not an error message, which
        is why pagination caps stay recoverable even on the `bare` variant.
        """
        out: dict[str, Any] = {"status": self.status, "body": self.body}
        if self.status == 200:
            return out
        if verbosity is Verbosity.VERBOSE:
            out["error"] = self.error_code
            out["fields"] = list(self.fields)
        elif verbosity is Verbosity.TERSE:
            out["error"] = self.error_code
        return out


def _err(status: int, code: str, *fields: str) -> Outcome:
    return Outcome(
        status=status,
        outcome_class=_STATUS_TO_CLASS[status],
        error_code=code,
        fields=tuple(fields),
        body={},
    )


def _as_int(value: Any, fallback: int) -> int:
    """Total int coercion, so the success path stays defined when a type rule
    is ablated and an off-type value gets through."""
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value


def _matches_type(value: Any, type_name: str) -> bool:
    if type_name == "int":
        # bool is an int subclass in Python; the API treats them as distinct.
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "str":
        return isinstance(value, str)
    if type_name == "bool":
        return isinstance(value, bool)
    raise ValueError(f"unknown type_name {type_name!r}")


def evaluate(contract: Contract, endpoint: str, params: dict[str, Any]) -> Outcome:
    """Apply the contract to one request. Deterministic: same input, same output.

    Rule precedence is fixed and structural-before-value, so that removing any
    single rule changes observable behaviour on at most the probes that rule
    governs. Ties within a stage break on the contract's rule order.
    """
    rules = contract.for_endpoint(endpoint)
    present = {k: v for k, v in params.items() if v is not None}

    def of(kind: RuleKind) -> list[Rule]:
        return [r for r in rules if r.kind is kind]

    # 1. Mutual exclusion (structural: the request shape itself is illegal).
    for r in of(RuleKind.MUTUAL_EXCLUSION):
        assert r.param_a and r.param_b
        if r.param_a in present and r.param_b in present:
            return _err(r.status, "mutually_exclusive", r.param_a, r.param_b)

    # 2. Missing required params.
    for r in of(RuleKind.REQUIRED):
        assert r.param
        if r.param not in present:
            return _err(r.status, "missing_required", r.param)

    # 3. Conditional dependencies (required only once a trigger is set).
    for r in of(RuleKind.CONDITIONAL_REQUIRED):
        assert r.if_param and r.then_param
        if present.get(r.if_param) == r.if_value and r.then_param not in present:
            return _err(r.status, "missing_required", r.then_param)

    # 4-7. Value-level checks on whatever was actually supplied.
    for r in of(RuleKind.TYPE):
        assert r.param and r.type_name
        if r.param in present and not _matches_type(present[r.param], r.type_name):
            return _err(r.status, "bad_type", r.param)

    for r in of(RuleKind.ENUM):
        assert r.param and r.values
        if r.param in present and present[r.param] not in r.values:
            return _err(r.status, "bad_enum", r.param)

    for r in of(RuleKind.RANGE):
        assert r.param
        v = present.get(r.param)
        if isinstance(v, int) and not isinstance(v, bool):
            if (r.lo is not None and v < r.lo) or (r.hi is not None and v > r.hi):
                return _err(r.status, "out_of_range", r.param)

    for r in of(RuleKind.FORMAT):
        assert r.param and r.pattern
        v = present.get(r.param)
        if isinstance(v, str) and not re.fullmatch(r.pattern, v):
            return _err(r.status, "bad_format", r.param)

    # 8. Resource lookup (only after the request itself is well-formed).
    for r in of(RuleKind.RESOURCE_LOOKUP):
        assert r.param
        if str(present.get(r.param)) not in SEEDED_ORDER_IDS:
            return _err(r.status, "not_found", r.param)

    return _success(contract, endpoint, present)


def _success(contract: Contract, endpoint: str, present: dict[str, Any]) -> Outcome:
    """Build the 200 body, applying defaults and the silent pagination cap."""
    rules = contract.for_endpoint(endpoint)
    defaults = {
        r.param: r.default for r in rules if r.kind is RuleKind.OPTIONAL and r.param
    }
    effective = {**defaults, **present}

    cap_rule = next((r for r in rules if r.kind is RuleKind.PAGINATION_CAP), None)
    if cap_rule is not None:
        assert cap_rule.param and cap_rule.cap is not None
        asked = _as_int(effective.get(cap_rule.param), _as_int(defaults.get(cap_rule.param), 0))
        granted = min(asked, cap_rule.cap)
        page = _as_int(effective.get("page"), _as_int(defaults.get("page"), 0))
        start = max(0, page * granted)
        count = max(0, min(granted, CATALOGUE_SIZE - start))
        body = {
            "items": [{"id": f"P-{start + i:04d}"} for i in range(count)],
            "count": count,
        }
        # TRUNCATED is observable purely from the body, at every verbosity.
        cls = OutcomeClass.TRUNCATED if granted < asked else OutcomeClass.OK
        return Outcome(200, cls, None, (), body)

    if endpoint == "POST /orders":
        return Outcome(200, OutcomeClass.OK, None, (), {"order_id": "ORD-1001"})

    return Outcome(200, OutcomeClass.OK, None, (), {"order_id": str(present.get("id"))})
