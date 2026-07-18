"""Analytic identifiability ceiling.

A rule is identifiable if some probe's observable outcome differs between the
contract and the contract with that rule negated. If no probe can tell the two
apart, no agent can ever recover it, so counting it against recall would
measure the problem's difficulty rather than the agent's skill.

Deterministic and LLM-free. The probe space is derived from the rules, so it
stays in sync with the contract by construction.

Ground truth. Agent code must never import this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from target_api.contract import (
    SEEDED_ORDER_IDS,
    Contract,
    Rule,
    RuleKind,
    evaluate,
)

OMITTED = object()  # sentinel: this probe leaves the param out entirely


@dataclass(frozen=True)
class Probe:
    endpoint: str
    params: dict[str, Any]

    def key(self) -> str:
        return f"{self.endpoint} {json.dumps(self.params, sort_keys=True, default=str)}"


def _valid_value(rules: list[Rule], param: str) -> Any:
    """A value for `param` that satisfies every rule mentioning it."""
    by_kind = {r.kind: r for r in rules}
    if RuleKind.RESOURCE_LOOKUP in by_kind:
        return SEEDED_ORDER_IDS[0]
    if RuleKind.FORMAT in by_kind:
        return by_kind[RuleKind.FORMAT].example
    if RuleKind.ENUM in by_kind:
        values = by_kind[RuleKind.ENUM].values
        assert values
        return values[0]
    if RuleKind.RANGE in by_kind:
        r = by_kind[RuleKind.RANGE]
        return r.lo if r.lo is not None else 1
    if RuleKind.PAGINATION_CAP in by_kind:
        return 5
    if RuleKind.TYPE in by_kind:
        return {"int": 1, "str": "x", "bool": True}[by_kind[RuleKind.TYPE].type_name or "str"]
    if RuleKind.OPTIONAL in by_kind:
        return by_kind[RuleKind.OPTIONAL].default
    return "x"


def _value_pool(rules: list[Rule], param: str) -> list[Any]:
    """Valid, omitted, and each way of violating the rules on this param."""
    pool: list[Any] = [OMITTED, _valid_value(rules, param)]
    for r in rules:
        if r.kind is RuleKind.TYPE:
            # A value of the wrong type, plus a string that looks like the right one.
            pool += {"int": ["abc", True], "str": [7], "bool": ["true", 1]}[r.type_name or "str"]
        elif r.kind is RuleKind.ENUM:
            pool.append("__not_a_member__")
        elif r.kind is RuleKind.RANGE:
            if r.lo is not None:
                pool.append(r.lo - 1)
            if r.hi is not None:
                pool += [r.hi, r.hi + 1]
        elif r.kind is RuleKind.FORMAT:
            pool.append("definitely not the right format")
        elif r.kind is RuleKind.PAGINATION_CAP:
            assert r.cap is not None
            pool += [1, r.cap - 1, r.cap, r.cap + 1, r.cap * 3]
        elif r.kind is RuleKind.RESOURCE_LOOKUP:
            pool.append("ORD-9999")

    seen: list[Any] = []
    for v in pool:
        if not any(v is s or (type(v) is type(s) and v == s) for s in seen):
            seen.append(v)
    return seen


def _baseline(contract: Contract, endpoint: str) -> dict[str, Any]:
    """Smallest request that satisfies the contract: required params only."""
    rules = list(contract.for_endpoint(endpoint))
    params: dict[str, Any] = {}
    for r in rules:
        if r.kind in (RuleKind.REQUIRED, RuleKind.RESOURCE_LOOKUP) and r.param:
            params[r.param] = _valid_value([x for x in rules if x.param == r.param], r.param)
    return params


def enumerate_probes(contract: Contract) -> list[Probe]:
    """Bounded probe space: one param at a time, plus combos for relational rules.

    One-at-a-time mirrors how the EIG agent probes once other factors are
    pinned, so the ceiling is measured against the same kind of isolating probe
    the agent actually sends.
    """
    probes: list[Probe] = []
    seen: set[str] = set()

    def add(endpoint: str, params: dict[str, Any]) -> None:
        clean = {k: v for k, v in params.items() if v is not OMITTED}
        p = Probe(endpoint, clean)
        if p.key() not in seen:
            seen.add(p.key())
            probes.append(p)

    for endpoint in contract.endpoints:
        rules = list(contract.for_endpoint(endpoint))
        base = _baseline(contract, endpoint)
        add(endpoint, base)

        for param in contract.params_of(endpoint):
            param_rules = [r for r in rules if r.param == param]
            for value in _value_pool(param_rules, param):
                add(endpoint, {**base, param: value})

        # Relational rules need both operands varied together.
        for r in rules:
            if r.kind is RuleKind.MUTUAL_EXCLUSION:
                assert r.param_a and r.param_b
                a = _valid_value([x for x in rules if x.param == r.param_a], r.param_a)
                b = _valid_value([x for x in rules if x.param == r.param_b], r.param_b)
                add(endpoint, {**base, r.param_a: a})
                add(endpoint, {**base, r.param_b: b})
                add(endpoint, {**base, r.param_a: a, r.param_b: b})
            elif r.kind is RuleKind.CONDITIONAL_REQUIRED:
                assert r.if_param and r.then_param
                then_v = _valid_value(
                    [x for x in rules if x.param == r.then_param], r.then_param
                )
                for trigger in (r.if_value, not r.if_value):
                    add(endpoint, {**base, r.if_param: trigger})
                    add(endpoint, {**base, r.if_param: trigger, r.then_param: then_v})

    return probes


def _negations(contract: Contract, rule: Rule) -> list[Contract]:
    """Contracts in which `rule` is false, but everything else still holds.

    For most kinds, deleting the rule is the negation. For a default it is not:
    the fallback may coincide with the declared default, making the contracts
    observationally identical even though the default is plainly discoverable.
    Negating a default means declaring a different one.
    """
    if rule.kind is RuleKind.OPTIONAL and isinstance(rule.default, int):
        other = rule.default + 1
        return [contract.replacing(rule.id, replace(rule, default=other))]
    return [contract.without(rule.id)]


def check(contract: Contract) -> dict[str, Any]:
    """Per-rule identifiability plus the achievable-recall ceiling."""
    probes = enumerate_probes(contract)
    verbosity = contract.verbosity

    baseline_obs = [evaluate(contract, p.endpoint, p.params).project(verbosity) for p in probes]

    results: dict[str, Any] = {}
    for rule in contract.rules:
        witness: str | None = None
        for negated in _negations(contract, rule):
            for probe, before in zip(probes, baseline_obs, strict=True):
                after = evaluate(negated, probe.endpoint, probe.params).project(verbosity)
                if before != after:
                    witness = probe.key()
                    break
            if witness:
                break
        results[rule.id] = {
            "identifiable": witness is not None,
            "prior_class": rule.prior_class.value,
            "kind": rule.kind.value,
            "witness_probe": witness,
        }

    achievable = [rid for rid, r in results.items() if r["identifiable"]]

    def count(pc: str, only_identifiable: bool) -> int:
        return sum(
            1
            for r in results.values()
            if r["prior_class"] == pc and (r["identifiable"] or not only_identifiable)
        )

    return {
        "variant": contract.name,
        "verbosity": verbosity.value,
        "probes_enumerated": len(probes),
        "total_rules": len(contract.rules),
        "achievable_rules": achievable,
        "ceiling": {
            "all": len(achievable) / len(contract.rules),
            "conventional": (
                count("conventional", True) / max(1, count("conventional", False))
            ),
            "counter_prior": (
                count("counter_prior", True) / max(1, count("counter_prior", False))
            ),
        },
        "rules": results,
    }


def main() -> None:
    from target_api.variants import VARIANTS

    out_dir = Path(__file__).resolve().parent.parent / "artifacts"
    out_dir.mkdir(exist_ok=True)

    for contract in VARIANTS.values():
        report = check(contract)
        path = out_dir / f"identifiability_{contract.name}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        print(f"\n=== {contract.name} (verbosity={report['verbosity']}) ===")
        print(f"probes enumerated : {report['probes_enumerated']}")
        print(
            f"identifiable      : {len(report['achievable_rules'])}/{report['total_rules']}"
        )
        for label, value in report["ceiling"].items():
            print(f"  ceiling[{label:<13}] = {value:.3f}")
        unreachable = [r for r, v in report["rules"].items() if not v["identifiable"]]
        if unreachable:
            print("UNIDENTIFIABLE (excluded from achievable recall):")
            for rid in unreachable:
                print(f"  - {rid}")
        print(f"written -> {path}")


if __name__ == "__main__":
    main()
