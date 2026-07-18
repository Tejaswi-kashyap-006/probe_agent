"""Baseline 1: probe at random.

The floor. It is handed a generic vocabulary of common REST parameter names,
because guessing parameter names from nothing at all is impossible and a floor
of exactly zero would say nothing useful. The vocabulary is deliberately
generic and is not the answer key: it contains names this API does not use, and
omits none of the difficulty, since knowing a parameter exists says nothing
about its type, bounds, domain, or error semantics.
"""

from __future__ import annotations

import random
from typing import Any

from probe.agents.base import Agent
from probe.client import Probe

PARAM_VOCAB = (
    "page", "limit", "offset", "sort", "order", "q", "query", "filter",
    "category", "status", "type", "name", "id", "user_id", "customer_id",
    "product_id", "sku", "quantity", "count", "size", "email", "phone",
    "currency", "expedited", "token", "format", "fields", "include",
)

VALUES: tuple[Any, ...] = (
    0, 1, 2, -1, 5, 10, 20, 37, 50, 100, 999,
    "1", "abc", "", "test", True, False,
    "pending", "shipped", "electronics", "a@b.com", "+15550001111",
    "CUS-000123", "P-0001", "ORD-1001",
)

PATH_IDS = ("ORD-1001", "ORD-9999", "1", "abc")


class RandomAgent(Agent):
    name = "random"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._rng = random.Random(self.seed)

    def step(self) -> None:
        endpoint = self._rng.choice(self.endpoints)
        method, path = endpoint.split(" ", 1)

        params = {
            self._rng.choice(PARAM_VOCAB): self._rng.choice(VALUES)
            for _ in range(self._rng.randint(0, 3))
        }

        if "{id}" in path:
            self.observe(Probe(method, path.replace("{id}", self._rng.choice(PATH_IDS))))
        elif method == "GET":
            self.observe(Probe(method, path, params=params))
        else:
            self.observe(Probe(method, path, body=params))
