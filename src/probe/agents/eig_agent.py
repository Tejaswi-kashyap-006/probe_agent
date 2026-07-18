"""The method: factored hypotheses plus information-theoretic probe selection.

Each step takes the factor it is least sure about, asks the model for requests
that would discriminate between that factor's surviving hypotheses, and sends
whichever candidate splits them most evenly. Every other factor is pinned to its
current best guess, so the probe varies one thing at a time: that is both the
controlled experiment and the practical answer to credit assignment, since an
isolating probe's outcome has an unambiguous cause.

It reports its contract without an LLM call, because the contract is just what
its factors currently believe.
"""

from __future__ import annotations

import random
from typing import Any

from probe.agents.base import Agent
from probe.client import Probe
from probe.eig.candidates import propose_probes
from probe.eig.scoring import best_probe, eig
from probe.hypothesis.predicate import endpoint_of
from probe.hypothesis.propose import build_factors, propose_surface, refill
from probe.hypothesis.space import FactorSet

# Deliberately tight. The budget divided by the factor count is roughly how
# many probes each parameter gets, and pinning one down properly takes closer
# to ten than to four. Carrying more factors buys coverage with depth, and at
# these budgets depth is what actually recovers rules.
MAX_FACTORS = 10
MAX_REFILLS_PER_STEP = 2
REDISCOVER_EVERY = 20


class EigAgent(Agent):
    name = "eig"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._rng = random.Random(self.seed)
        self.factors = FactorSet(endpoints=self.endpoints)
        self._sent: list[str] = []
        self._named_params: set[tuple[str, str]] = set()
        self._floor = 8
        self._bootstrapped = False

    # -- setup ---------------------------------------------------------------

    def _bootstrap(self) -> None:
        """Probe each endpoint a few ways before deciding what to model.

        Naming the parameters off a single request per endpoint produces
        factors for things that do not exist and none for things that do, and
        those factors are then frozen for the whole run.
        """
        for endpoint in self.endpoints:
            method, path = endpoint.split(" ", 1)
            self._send(Probe(method, path.replace("{id}", "ORD-1001")))
            if "{id}" not in path:
                # An empty request names the required parameters for free.
                self._send(
                    Probe(method, path, body={}) if method == "POST" else
                    Probe(method, path, params={"limit": 100})
                )
        self._discover()
        self._bootstrapped = True

    def _discover(self) -> None:
        """Add factors for parameters the evidence now suggests exist."""
        params, relations = propose_surface(
            self.llm, self.endpoints, self.evidence.render()
        )
        # A parameter the API named in an error definitely exists, which is
        # better evidence than anything the model can guess. These go first.
        confirmed = [
            {"endpoint": endpoint, "param": param}
            for endpoint, param in sorted(self._named_params)
        ]
        discovered = build_factors(
            confirmed + params, relations, self.endpoints, max_relations=2
        )

        existing = {f.name for f in self.factors.factors}
        room = MAX_FACTORS - len(self.factors.factors)
        added = [f for f in discovered.factors if f.name not in existing][:room]

        for factor in added:
            proposed, _ = refill(self.llm, factor, self.evidence.render(), self._floor)
            factor.add(proposed)
            self.factors.factors.append(factor)

        if added:
            self.trace.write(
                "factors_built",
                added=[f.name for f in added],
                factors=[f.name for f in self.factors.factors],
                particles=self.factors.total_particles(),
                probes_used=self.client.used,
            )

    # -- main loop -----------------------------------------------------------

    def step(self) -> None:
        if not self._bootstrapped:
            self._bootstrap()
            return

        target = self.factors.target()
        if target is None:
            self._refill_thin()
            target = self.factors.target()
            if target is None:
                # Nothing left in doubt: spend what remains confirming.
                self._send(self._fallback_probe())
                return

        candidates = propose_probes(
            self.llm, target, self.evidence.render(), self._sent, self.llm_candidates
        )
        candidates = [p for p in candidates if p.key() not in set(self._sent)]

        entropy_before = target.entropy()
        probe, score, buckets = best_probe(candidates, target, self.factors, self._rng)
        if probe is None:
            probe = self._fallback_probe()
            score, buckets = 0.0, {}

        self.trace.write(
            "eig",
            target_factor=target.name,
            target_entropy=round(target.entropy(), 4),
            chosen=probe.describe(),
            eig=round(score, 4),
            partition=buckets,
            candidates=len(candidates),
            candidate_scores=[round(eig(c, target, self.factors), 4) for c in candidates],
        )

        result = self._send(probe)
        if result is None:
            return

        # Only the factor this probe was chosen to isolate is judged by it.
        events = self.factors.eliminate(probe, result, only=target.name)
        for event in events:
            self.trace.write("hypothesis_death", **event)

        self.factors.note_target_outcome(target, entropy_before)
        self.factors.refresh_map()
        self._refill_empty()

        if self.client.used % REDISCOVER_EVERY == 0:
            self._discover()

    # -- helpers -------------------------------------------------------------

    def _send(self, probe: Probe) -> Any:
        self._sent.append(probe.key())
        result = self.observe(probe)
        if result is not None and result.fields:
            endpoint = endpoint_of(probe, self.endpoints)
            for param in result.fields:
                self._named_params.add((endpoint, param))
        return result

    def _fallback_probe(self) -> Probe:
        """Something unsent, when the model offers nothing usable."""
        for _ in range(20):
            probe = Probe(
                "GET", "/products", params={"limit": self._rng.randint(1, 60)}
            )
            if probe.key() not in set(self._sent):
                return probe
        return Probe("GET", "/products")

    def _refill_empty(self) -> None:
        """Re-propose only the factors that emptied, never the whole contract."""
        refilled = 0
        for factor in self.factors.empty_factors():
            if refilled >= MAX_REFILLS_PER_STEP:
                break
            proposed, was_empty = refill(
                self.llm, factor, self.evidence.render(), self._floor
            )
            factor.add(proposed)
            factor.reproposals += 1
            refilled += 1
            # Every hypothesis it held was wrong. This is the agent being
            # genuinely surprised, and it is worth seeing in the trace.
            self.trace.write(
                "reproposal",
                factor=factor.name,
                from_empty=was_empty,
                new_particles=len(proposed),
                probes_used=self.client.used,
            )

    def _refill_thin(self) -> None:
        thin = [f for f in self.factors.factors if len(f.particles) <= 1]
        for factor in thin[:MAX_REFILLS_PER_STEP]:
            proposed, _ = refill(self.llm, factor, self.evidence.render(), self._floor)
            factor.add(proposed)

    @property
    def llm_candidates(self) -> int:
        return 10

    def report_contract(self) -> list[dict[str, Any]]:
        """The MAP contract. No LLM call: this is simply what it believes."""
        return self.factors.reported_rules()

