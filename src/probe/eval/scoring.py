"""Score a recovered contract against ground truth.

Rules are compared by behaviour, not by syntax. Two rules are the same rule if
they classify the same values the same way, so `1 <= quantity <= 99` matches
`quantity in range(1, 100)` while an off-by-one bound does not: the two differ
on the boundary value, and the boundary is always in the comparison corpus.

Both sides arrive as plain dicts. This module never imports the ground truth;
the harness passes it in as data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Fixed corpus for deciding whether two format patterns mean the same thing.
# Regex equivalence is undecidable in general, so equivalence is defined as
# agreeing on every string here.
#
# Membership is deliberately restricted to strings where any reasonable
# implementation of the same intent agrees. Awkward-but-valid emails such as
# first.last@example.co.uk are excluded: real email regexes disagree about them
# constantly, and treating that disagreement as "a different rule" would fail
# an agent that recovered the constraint perfectly well. What remains still
# separates every format these contracts use.
FORMAT_CORPUS: tuple[str, ...] = (
    "a@b.com",
    "user@example.com",
    "no-at-sign.com",
    "@example.com",
    "trailing@",
    "CUS-000123",
    "CUS-12345",
    "CUS-1234567",
    "cus-000123",
    "CUSTOMER-000123",
    "WH-AB12",
    "WH-ab12",
    "WH-ABC12",
    "+15550001111",
    "5550001111",
    "555",
    "12345678901234567890",
    "",
    "x",
)

_KIND_ALIASES = {
    "required": "required",
    "require": "required",
    "mandatory": "required",
    "optional": "optional",
    "default": "optional",
    "type": "type",
    "type_constraint": "type",
    "range": "range",
    "bounds": "range",
    "min_max": "range",
    "enum": "enum",
    "one_of": "enum",
    "enum_domain": "enum",
    "allowed_values": "enum",
    "format": "format",
    "pattern": "format",
    "regex": "format",
    "conditional_required": "conditional_required",
    "conditional": "conditional_required",
    "dependency": "conditional_required",
    "mutual_exclusion": "mutual_exclusion",
    "mutually_exclusive": "mutual_exclusion",
    "exclusive": "mutual_exclusion",
    "pagination_cap": "pagination_cap",
    "cap": "pagination_cap",
    "limit_cap": "pagination_cap",
    "resource_lookup": "resource_lookup",
    "not_found": "resource_lookup",
}

_TYPE_ALIASES = {
    "int": "int",
    "integer": "int",
    "number": "int",
    "str": "str",
    "string": "str",
    "text": "str",
    "bool": "bool",
    "boolean": "bool",
}


@dataclass(frozen=True)
class NormRule:
    """A rule reduced to identity plus a behavioural signature."""

    endpoint: str
    kind: str
    params: tuple[str, ...]
    signature: Any
    status: int | None
    rule_id: str | None = None
    prior_class: str | None = None

    def identity(self) -> tuple[Any, ...]:
        """What makes two rules the same rule. Deliberately excludes status."""
        return (self.endpoint, self.kind, self.params, self.signature)


def _norm_endpoint(raw: Any) -> str:
    text = str(raw or "").strip()
    match = re.match(r"(?i)^(get|post|put|patch|delete)\s+(\S+)$", text)
    if match:
        return f"{match.group(1).upper()} {match.group(2)}"
    match = re.match(r"(?i)^(\S+)\s+(get|post|put|patch|delete)$", text)
    if match:
        return f"{match.group(2).upper()} {match.group(1)}"
    return text


def _norm_kind(raw: Any) -> str:
    key = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _KIND_ALIASES.get(key, key)


def _get(rule: dict[str, Any], *names: str) -> Any:
    """First present field among several spellings of the same idea."""
    for name in names:
        if rule.get(name) is not None:
            return rule[name]
    return None


def _bounds(rule: dict[str, Any]) -> tuple[Any, Any]:
    """Inclusive bounds, converting exclusive ones. Integers throughout."""
    lo = _get(rule, "lo", "min", "minimum", "gte", "min_inclusive")
    hi = _get(rule, "hi", "max", "maximum", "lte", "max_inclusive")
    gt = _get(rule, "gt", "exclusive_min", "min_exclusive")
    lt = _get(rule, "lt", "exclusive_max", "max_exclusive")
    if lo is None and isinstance(gt, int) and not isinstance(gt, bool):
        lo = gt + 1
    if hi is None and isinstance(lt, int) and not isinstance(lt, bool):
        hi = lt - 1
    return lo, hi


def _range_signature(lo: Any, hi: Any) -> tuple[str, ...]:
    """Accept/reject over the integers around both bounds, so off-by-one shows."""
    lo_i = lo if isinstance(lo, int) and not isinstance(lo, bool) else None
    hi_i = hi if isinstance(hi, int) and not isinstance(hi, bool) else None
    anchors = [v for v in (lo_i, hi_i) if v is not None] or [0]
    start, stop = min(anchors) - 2, max(anchors) + 2
    # Keep the sweep bounded for absurd values while still covering both edges.
    if stop - start > 400:
        probes = sorted({start, start + 1, stop - 1, stop, *anchors})
        probes += [v + 1 for v in anchors] + [v - 1 for v in anchors]
        candidates = sorted(set(probes))
    else:
        candidates = list(range(start, stop + 1))
    accepted = [
        str(v)
        for v in candidates
        if (lo_i is None or v >= lo_i) and (hi_i is None or v <= hi_i)
    ]
    return tuple(accepted)


def _format_signature(pattern: Any) -> tuple[bool, ...]:
    """Which corpus strings the pattern accepts. Equivalent patterns agree."""
    try:
        compiled = re.compile(str(pattern or ""))
    except re.error:
        return tuple(False for _ in FORMAT_CORPUS)
    return tuple(bool(compiled.fullmatch(s)) for s in FORMAT_CORPUS)


def normalize(rule: dict[str, Any]) -> NormRule | None:
    """Reduce one rule dict to comparable form. Returns None if unintelligible."""
    kind = _norm_kind(rule.get("kind"))
    endpoint = _norm_endpoint(_get(rule, "endpoint", "route", "path"))
    param = str(_get(rule, "param", "parameter", "field", "name") or "").strip()
    status = _get(rule, "status", "status_code", "http_status")
    status = status if isinstance(status, int) and not isinstance(status, bool) else None
    common = {
        "endpoint": endpoint,
        "status": status,
        "rule_id": rule.get("id"),
        "prior_class": rule.get("prior_class"),
    }

    if kind in ("required", "resource_lookup"):
        if not param:
            return None
        return NormRule(kind=kind, params=(param,), signature=None, **common)

    if kind == "optional":
        if not param:
            return None
        default = _get(rule, "default", "default_value", "defaults_to")
        return NormRule(
            kind=kind, params=(param,), signature=("default", default), **common
        )

    if kind == "type":
        raw_type = _get(rule, "type_name", "type", "expected_type", "datatype")
        type_name = _TYPE_ALIASES.get(str(raw_type or "").strip().lower())
        if not param or not type_name:
            return None
        return NormRule(kind=kind, params=(param,), signature=type_name, **common)

    if kind == "range":
        if not param:
            return None
        lo, hi = _bounds(rule)
        if lo is None and hi is None:
            return None
        return NormRule(
            kind=kind, params=(param,), signature=_range_signature(lo, hi), **common
        )

    if kind == "enum":
        values = _get(rule, "values", "allowed", "allowed_values", "enum", "options") or ()
        if not param or not isinstance(values, (list, tuple)) or not values:
            return None
        return NormRule(
            kind=kind,
            params=(param,),
            signature=tuple(sorted(str(v) for v in values)),
            **common,
        )

    if kind == "format":
        if not param:
            return None
        pattern = _get(rule, "pattern", "regex", "format", "matches")
        return NormRule(
            kind=kind, params=(param,), signature=_format_signature(pattern), **common
        )

    if kind == "pagination_cap":
        if not param:
            return None
        cap = _get(rule, "cap", "max", "maximum", "capped_at", "limit")
        return NormRule(kind=kind, params=(param,), signature=("cap", cap), **common)

    if kind == "conditional_required":
        if_param = str(_get(rule, "if_param", "when_param", "trigger_param") or "").strip()
        then_param = str(
            _get(rule, "then_param", "requires", "required_param") or ""
        ).strip()
        if not if_param or not then_param:
            return None
        if_value = _get(rule, "if_value", "when_value", "trigger_value")
        return NormRule(
            kind=kind,
            params=(if_param, then_param),
            signature=("if_value", str(if_value).lower()),
            **common,
        )

    if kind == "mutual_exclusion":
        a = str(_get(rule, "param_a", "first", "left") or "").strip()
        b = str(_get(rule, "param_b", "second", "right") or "").strip()
        if not a and not b:
            pair = _get(rule, "params", "parameters", "fields")
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                a, b = str(pair[0]).strip(), str(pair[1]).strip()
        if not a or not b:
            return None
        return NormRule(
            kind=kind, params=tuple(sorted((a, b))), signature=None, **common
        )

    return None


@dataclass(frozen=True)
class Score:
    precision: float
    recall: float
    f1: float
    true_positives: int
    false_positives: int
    false_negatives: int
    matched_rule_ids: tuple[str, ...]
    missed_rule_ids: tuple[str, ...]
    hallucinated: tuple[str, ...]
    error_semantics_accuracy: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "matched_rule_ids": list(self.matched_rule_ids),
            "missed_rule_ids": list(self.missed_rule_ids),
            "hallucinated": list(self.hallucinated),
            "error_semantics_accuracy": (
                None
                if self.error_semantics_accuracy is None
                else round(self.error_semantics_accuracy, 4)
            ),
        }


def _f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def score(
    reported: list[dict[str, Any]],
    truth: list[dict[str, Any]],
) -> Score:
    """Precision, recall and F1 of a reported contract against ground truth.

    Status is not part of rule identity: a rule found with the wrong error code
    counts as found, and the status is reported separately as error-semantics
    accuracy. Scoring it as identity would penalise the same mistake twice,
    once as a miss and once as a hallucination.
    """
    truth_norm = [n for n in (normalize(r) for r in truth) if n is not None]
    reported_norm = [n for n in (normalize(r) for r in reported) if n is not None]

    unmatched = list(truth_norm)
    matched: list[tuple[NormRule, NormRule]] = []
    hallucinated: list[NormRule] = []
    seen: set[tuple[Any, ...]] = set()

    for candidate in reported_norm:
        identity = candidate.identity()
        if identity in seen:
            continue  # a duplicate claim is not a second discovery
        seen.add(identity)
        hit = next((t for t in unmatched if t.identity() == identity), None)
        if hit is None:
            hallucinated.append(candidate)
        else:
            unmatched.remove(hit)
            matched.append((hit, candidate))

    tp, fp, fn = len(matched), len(hallucinated), len(unmatched)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0

    with_status = [(t, c) for t, c in matched if t.status is not None]
    accuracy = (
        sum(1 for t, c in with_status if t.status == c.status) / len(with_status)
        if with_status
        else None
    )

    return Score(
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        matched_rule_ids=tuple(t.rule_id or "" for t, _ in matched),
        missed_rule_ids=tuple(t.rule_id or "" for t in unmatched),
        hallucinated=tuple(f"{h.kind}:{'+'.join(h.params)}" for h in hallucinated),
        error_semantics_accuracy=accuracy,
    )


def score_by_subset(
    reported: list[dict[str, Any]],
    truth: list[dict[str, Any]],
    achievable: set[str] | None = None,
) -> dict[str, Any]:
    """Score overall and per prior_class, restricted to identifiable rules.

    The counter_prior subset is the one that separates recovering a contract
    from recalling API conventions, so it is always reported on its own.
    """
    if achievable is not None:
        truth = [r for r in truth if r.get("id") in achievable]

    result: dict[str, Any] = {"all": score(reported, truth).as_dict()}
    for subset in ("conventional", "counter_prior"):
        subset_truth = [r for r in truth if r.get("prior_class") == subset]
        if subset_truth:
            # Hallucinations cannot be attributed to a subset, so subset
            # precision is left out and only recall is meaningful here.
            subset_score = score(reported, subset_truth)
            result[subset] = {
                "recall": round(subset_score.recall, 4),
                "found": subset_score.true_positives,
                "total": len(subset_truth),
                "missed_rule_ids": list(subset_score.missed_rule_ids),
            }
    return result
