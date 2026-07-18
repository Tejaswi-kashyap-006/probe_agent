"""The closed rule grammar agents emit, and its interpreter.

Model output is data, never code. Rules are validated against a fixed set of
kinds with typed fields and then interpreted, so no model-authored Python is
ever executed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

OutcomeClass = str  # "OK" | "TRUNCATED" | "400" | "404" | "409" | "422"

KINDS = (
    "required",
    "optional",
    "type",
    "range",
    "enum",
    "format",
    "conditional_required",
    "mutual_exclusion",
    "pagination_cap",
)

_TYPES = ("int", "str", "bool")

GRAMMAR_PROMPT = """A contract rule is a JSON object. Only these kinds exist:

{"kind":"required","endpoint":E,"param":P,"status":S}
{"kind":"optional","endpoint":E,"param":P,"default":V}
{"kind":"type","endpoint":E,"param":P,"type_name":"int"|"str"|"bool","status":S}
{"kind":"range","endpoint":E,"param":P,"lo":N,"hi":N,"status":S}
{"kind":"enum","endpoint":E,"param":P,"values":[...],"status":S}
{"kind":"format","endpoint":E,"param":P,"pattern":"<regex>","status":S}
{"kind":"conditional_required","endpoint":E,"if_param":P,"if_value":V,"then_param":P,"status":S}
{"kind":"mutual_exclusion","endpoint":E,"param_a":P,"param_b":P,"status":S}
{"kind":"pagination_cap","endpoint":E,"param":P,"cap":N}

E is one of the endpoints you were given, exactly as written.
S is the HTTP status the violation returns. Do not assume conventional codes.
Emit no other keys and no prose."""


@dataclass(frozen=True)
class Rule:
    kind: str
    endpoint: str
    param: str | None = None
    status: int | None = None
    default: Any = None
    type_name: str | None = None
    lo: int | None = None
    hi: int | None = None
    values: tuple[str, ...] | None = None
    pattern: str | None = None
    if_param: str | None = None
    if_value: Any = None
    then_param: str | None = None
    param_a: str | None = None
    param_b: str | None = None
    cap: int | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "endpoint": self.endpoint}
        for name in (
            "param",
            "status",
            "default",
            "type_name",
            "lo",
            "hi",
            "pattern",
            "if_param",
            "if_value",
            "then_param",
            "param_a",
            "param_b",
            "cap",
        ):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        if self.values is not None:
            out["values"] = list(self.values)
        return out


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def parse_rule(raw: Any) -> Rule | None:
    """Validate one model-emitted rule. Returns None if it is not well formed."""
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip().lower()
    endpoint = str(raw.get("endpoint") or "").strip()
    if kind not in KINDS or not endpoint:
        return None

    param = raw.get("param")
    param = str(param).strip() if param is not None else None
    status = _as_int(raw.get("status"))

    common = {"kind": kind, "endpoint": endpoint, "status": status}

    if kind in ("required",):
        return Rule(param=param, **common) if param else None
    if kind == "optional":
        return Rule(param=param, default=raw.get("default"), **common) if param else None
    if kind == "type":
        type_name = str(raw.get("type_name") or "").strip().lower()
        if not param or type_name not in _TYPES:
            return None
        return Rule(param=param, type_name=type_name, **common)
    if kind == "range":
        lo, hi = _as_int(raw.get("lo")), _as_int(raw.get("hi"))
        if not param or (lo is None and hi is None):
            return None
        return Rule(param=param, lo=lo, hi=hi, **common)
    if kind == "enum":
        values = raw.get("values")
        if not param or not isinstance(values, list) or not values:
            return None
        return Rule(param=param, values=tuple(str(v) for v in values), **common)
    if kind == "format":
        pattern = raw.get("pattern")
        if not param or not isinstance(pattern, str):
            return None
        try:
            re.compile(pattern)
        except re.error:
            return None
        return Rule(param=param, pattern=pattern, **common)
    if kind == "conditional_required":
        if_param = str(raw.get("if_param") or "").strip()
        then_param = str(raw.get("then_param") or "").strip()
        if not if_param or not then_param:
            return None
        return Rule(
            if_param=if_param,
            if_value=raw.get("if_value"),
            then_param=then_param,
            **common,
        )
    if kind == "mutual_exclusion":
        a = str(raw.get("param_a") or "").strip()
        b = str(raw.get("param_b") or "").strip()
        return Rule(param_a=a, param_b=b, **common) if a and b else None
    if kind == "pagination_cap":
        cap = _as_int(raw.get("cap"))
        return Rule(param=param, cap=cap, **common) if param and cap is not None else None
    return None


def parse_rules(raw: Any) -> list[Rule]:
    """Validate a list of model-emitted rules, dropping anything malformed."""
    if not isinstance(raw, list):
        return []
    parsed = [parse_rule(item) for item in raw]
    return [r for r in parsed if r is not None]


def matches_type(value: Any, type_name: str) -> bool:
    if type_name == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "bool":
        return isinstance(value, bool)
    return isinstance(value, str)


def violation(rule: Rule, params: dict[str, Any]) -> int | None:
    """The status this rule would return for these params, or None if satisfied.

    Pure interpretation of validated data. Never executes model-authored code.
    """
    present = {k: v for k, v in params.items() if v is not None}

    if rule.kind == "required":
        return rule.status or 422 if rule.param not in present else None
    if rule.kind == "conditional_required":
        triggered = present.get(rule.if_param) == rule.if_value
        return rule.status or 422 if triggered and rule.then_param not in present else None
    if rule.kind == "mutual_exclusion":
        both = rule.param_a in present and rule.param_b in present
        return rule.status or 400 if both else None

    if rule.param not in present:
        return None
    value = present[rule.param]

    if rule.kind == "type":
        return rule.status or 400 if not matches_type(value, rule.type_name or "str") else None
    if rule.kind == "enum":
        return rule.status or 400 if str(value) not in (rule.values or ()) else None
    if rule.kind == "range":
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        below = rule.lo is not None and value < rule.lo
        above = rule.hi is not None and value > rule.hi
        return rule.status or 400 if below or above else None
    if rule.kind == "format":
        if not isinstance(value, str):
            return None
        return rule.status or 400 if not re.fullmatch(rule.pattern or "", value) else None
    return None
