"""Expected information gain of a probe.

Because every hypothesis predicts a probe's outcome deterministically, the
expectation over outcomes collapses into the entropy of the partition the probe
induces over the surviving particles. No nested Monte Carlo, no LLM call per
hypothesis per probe: just a function call each. That collapse is the whole
reason this runs in minutes instead of costing hundreds of dollars.

The best probe splits the survivors most evenly, which is a binary search
through contract space. A probe every hypothesis agrees on scores zero, and
those are exactly the probes the naive agents spend their budget on.
"""

from __future__ import annotations

from collections import defaultdict
from math import log2

from probe.client import Probe
from probe.hypothesis.space import Factor, FactorSet


def partition(probe: Probe, factor: Factor, factors: FactorSet) -> dict[str, float]:
    """Weight of surviving particles by the outcome each one predicts."""
    buckets: dict[str, float] = defaultdict(float)
    for particle in factor.particles:
        buckets[factors.predict_with(factor, particle, probe)] += 1.0
    return dict(buckets)


def entropy(buckets: dict[str, float]) -> float:
    total = sum(buckets.values())
    if total <= 0:
        return 0.0
    return -sum((w / total) * log2(w / total) for w in buckets.values() if w > 0)


def eig(probe: Probe, factor: Factor, factors: FactorSet) -> float:
    """EIG is the entropy of the partition this probe induces."""
    return entropy(partition(probe, factor, factors))


def best_probe(
    probes: list[Probe], factor: Factor, factors: FactorSet
) -> tuple[Probe | None, float, dict[str, float]]:
    """The candidate that splits the target factor most evenly."""
    best: tuple[Probe | None, float, dict[str, float]] = (None, -1.0, {})
    for probe in probes:
        buckets = partition(probe, factor, factors)
        score = entropy(buckets)
        if score > best[1]:
            best = (probe, score, buckets)
    return best
