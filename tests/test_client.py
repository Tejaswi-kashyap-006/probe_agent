"""Probe budget and caching."""

from __future__ import annotations

import pytest

from probe.client import BudgetExhausted, Probe, ProbeClient


def test_every_probe_counts_against_budget(base_url: str) -> None:
    client = ProbeClient(base_url=base_url, budget=3)
    for _ in range(3):
        client.send(Probe("GET", "/products"))
    assert client.used == 3
    assert client.remaining == 0
    with pytest.raises(BudgetExhausted):
        client.send(Probe("GET", "/products"))
    client.close()


def test_repeat_probes_are_served_from_cache_but_still_cost_budget(base_url: str) -> None:
    client = ProbeClient(base_url=base_url, budget=5)
    first = client.send(Probe("GET", "/products", params={"limit": 3}))
    second = client.send(Probe("GET", "/products", params={"limit": 3}))

    assert first.cached is False
    assert second.cached is True
    assert second.body == first.body
    # A repeat teaches nothing, but in the real world you still sent it.
    assert client.used == 2
    client.close()


def test_result_carries_what_the_variant_leaks(base_url: str) -> None:
    client = ProbeClient(base_url=base_url, budget=2)
    result = client.send(Probe("POST", "/orders", body={"quantity": 2}))
    assert result.status == 422
    assert result.error == "missing_required"
    assert result.fields == ("customer_id",)
    client.close()
