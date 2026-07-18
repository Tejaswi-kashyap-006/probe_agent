"""Aggregate a run summary across seeds into mean and spread.

A single run proves nothing, so nothing here reports one. Every figure is a
mean with its range across seeds, and the counter-prior subset is always shown
on its own.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def _fmt(values: list[float]) -> str:
    if not values:
        return "-"
    mean = statistics.mean(values)
    if len(values) == 1:
        return f"{mean:.3f}"
    return f"{mean:.3f} [{min(values):.3f}-{max(values):.3f}]"


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate results across seeds")
    parser.add_argument("summary")
    args = parser.parse_args()

    runs: list[dict[str, Any]] = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[(run["variant"], run["agent"])].append(run)

    header = (
        f"{'variant':<8} {'agent':<11} {'F1':<20} {'conventional':<20} "
        f"{'counter-prior':<20} {'seeds':<6} {'LLM':<7} {'cost'}"
    )
    print(header)
    print("-" * len(header))

    for (variant, agent), group in sorted(grouped.items()):
        f1 = [g["score"]["all"]["f1"] for g in group]
        conv = [g["score"].get("conventional", {}).get("recall", 0.0) for g in group]
        cp = [g["score"].get("counter_prior", {}).get("recall", 0.0) for g in group]
        calls = statistics.mean(g["llm_calls"] for g in group)
        cost = sum(g["cost_usd"] for g in group)
        print(
            f"{variant:<8} {agent:<11} {_fmt(f1):<20} {_fmt(conv):<20} "
            f"{_fmt(cp):<20} {len(group):<6} {calls:<7.0f} ${cost:.3f}"
        )

    print(f"\ntotal cost across all runs: ${sum(r['cost_usd'] for r in runs):.3f}")


if __name__ == "__main__":
    main()
