"""Ablation: the same hypothesis machinery, without EIG selection.

It maintains the identical factored posterior, gets the identical candidate
probes from the identical prompt, and eliminates hypotheses identically. The
only difference is that it picks a candidate at random instead of picking the
one that splits the surviving hypotheses most evenly.

Any gap between this and the EIG agent is attributable to the selection rule
alone, which is the claim actually under test. Any gap between this and ReAct
is attributable to tracking hypotheses at all.
"""

from __future__ import annotations

from probe.agents.eig_agent import EigAgent
from probe.eig.candidates import propose_probes
from probe.eig.scoring import entropy, partition


class HypothesisAgent(EigAgent):
    name = "hypothesis"

    def step(self) -> None:
        if not self._bootstrapped:
            self._bootstrap()
            return

        target = self.factors.target()
        if target is None:
            self._refill_thin()
            target = self.factors.target()
            if target is None:
                self._send(self._fallback_probe())
                return

        candidates = propose_probes(
            self.llm, target, self.evidence.render(), self._sent, self.llm_candidates
        )
        candidates = [p for p in candidates if p.key() not in set(self._sent)]

        probe = self._rng.choice(candidates) if candidates else self._fallback_probe()

        # Scored only so the trace can show what this choice was worth; the
        # score plays no part in choosing it.
        buckets = partition(probe, target, self.factors)
        self.trace.write(
            "eig",
            target_factor=target.name,
            target_entropy=round(target.entropy(), 4),
            chosen=probe.describe(),
            eig=round(entropy(buckets), 4),
            partition=buckets,
            candidates=len(candidates),
            selection="random",
        )

        result = self._send(probe)
        if result is None:
            return

        for event in self.factors.eliminate(probe, result, only=target.name):
            self.trace.write("hypothesis_death", **event)

        self.factors.refresh_map()
        self._refill_empty()
