"""EIG must behave like the entropy of the partition a probe induces.

Two properties carry the method: a probe every hypothesis agrees on is worth
nothing, and a probe that splits them evenly is worth the most available.
"""

from __future__ import annotations

from math import log2

from probe.client import Probe
from probe.eig.scoring import best_probe, eig, entropy, partition
from probe.hypothesis.rules import Rule
from probe.hypothesis.space import Factor, FactorSet, Particle

ENDPOINTS = ("GET /products", "POST /orders")


def _cap_factor(caps: list[int]) -> tuple[Factor, FactorSet]:
    """One factor whose particles disagree only about where limit caps."""
    factor = Factor(name="GET /products::limit", endpoint="GET /products", kind="parameter")
    factor.add(
        [
            Particle((Rule(kind="pagination_cap", endpoint="GET /products", param="limit", cap=c),))
            for c in caps
        ]
    )
    return factor, FactorSet(factors=[factor], endpoints=ENDPOINTS)


def test_probe_every_hypothesis_agrees_on_scores_zero() -> None:
    factor, factors = _cap_factor([10, 20, 30, 40])
    # Asking for 5 is under every candidate cap, so all of them predict OK.
    probe = Probe("GET", "/products", params={"limit": 5})

    assert len(partition(probe, factor, factors)) == 1
    assert eig(probe, factor, factors) == 0.0


def test_evenly_splitting_probe_scores_the_maximum() -> None:
    factor, factors = _cap_factor([10, 30])
    # 20 is above one cap and below the other, so the two disagree.
    probe = Probe("GET", "/products", params={"limit": 20})

    assert eig(probe, factor, factors) == 1.0, "one bit from a clean two-way split"


def test_eig_is_bounded_by_log2_of_the_particle_count() -> None:
    factor, factors = _cap_factor([5, 15, 25, 35])
    probes = [Probe("GET", "/products", params={"limit": n}) for n in range(1, 60)]
    for probe in probes:
        assert eig(probe, factor, factors) <= log2(len(factor.particles)) + 1e-9


def test_best_probe_prefers_the_even_split_over_the_lopsided_one() -> None:
    factor, factors = _cap_factor([10, 20, 30, 40])
    lopsided = Probe("GET", "/products", params={"limit": 45})  # all four agree
    even = Probe("GET", "/products", params={"limit": 25})  # splits two and two

    chosen, score, buckets = best_probe([lopsided, even], factor, factors)
    assert chosen == even
    assert score == 1.0
    assert sorted(buckets.values()) == [2.0, 2.0]


def test_entropy_of_an_even_partition_is_log2_of_its_width() -> None:
    assert entropy({"a": 1, "b": 1, "c": 1, "d": 1}) == 2.0
    assert entropy({"a": 3}) == 0.0
    assert entropy({}) == 0.0


def test_a_probe_that_kills_the_wrong_hypotheses_leaves_the_right_one() -> None:
    factor, factors = _cap_factor([10, 20, 37, 50])
    probe = Probe("GET", "/products", params={"limit": 40})

    # Caps below 40 truncate; caps at or above 40 do not.
    buckets = partition(probe, factor, factors)
    assert buckets == {"TRUNCATED": 3.0, "OK": 1.0}


def test_factor_entropy_is_log2_of_survivors() -> None:
    factor, _ = _cap_factor([1, 2, 3, 4, 5, 6, 7, 8])
    assert factor.entropy() == 3.0
    del factor.particles[1:]
    assert factor.entropy() == 0.0


def test_duplicate_particles_are_rejected() -> None:
    factor, _ = _cap_factor([10, 20])
    before = len(factor.particles)
    factor.add(
        [
            Particle(
                (Rule(kind="pagination_cap", endpoint="GET /products", param="limit", cap=10),)
            )
        ]
    )
    # A factor whose particles agree has zero EIG for every probe, so letting
    # duplicates in would quietly stall the agent.
    assert len(factor.particles) == before
