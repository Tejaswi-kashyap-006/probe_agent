"""Shared agent interface.

Every agent reports its contract on the same schedule, so the recovery curve
and probes-to-recall are measured identically across arms rather than depending
on when each agent happens to volunteer an answer.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from probe.client import BudgetExhausted, Probe, ProbeClient, ProbeResult
from probe.evidence import Evidence
from probe.hypothesis.rules import GRAMMAR_PROMPT, parse_rules
from probe.llm import LLMClient
from probe.trace import Trace

CHECKPOINT_EVERY = 10

REPORT_SYSTEM = """You are reverse-engineering an undocumented HTTP API.
Report the contract you have established from the evidence.

Report only what the evidence supports. An invented constraint costs you as
much as a missed one. Do not assume conventional values: this API may cap,
index, or number things differently from the APIs you have seen before.

""" + GRAMMAR_PROMPT + """

Reply with JSON: {"rules":[...]}"""


@dataclass
class RunResult:
    agent: str
    variant: str
    seed: int
    reported_contract: list[dict[str, Any]]
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    probes_used: int = 0
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    elapsed_s: float = 0.0


class Agent(ABC):
    name = "base"

    def __init__(
        self,
        client: ProbeClient,
        llm: LLMClient,
        trace: Trace,
        endpoints: tuple[str, ...],
        variant: str,
        seed: int,
    ) -> None:
        self.client = client
        self.llm = llm
        self.trace = trace
        self.endpoints = endpoints
        self.variant = variant
        self.seed = seed
        self.evidence = Evidence()

    @abstractmethod
    def step(self) -> None:
        """Send exactly one probe."""

    def observe(self, probe: Probe) -> ProbeResult | None:
        """Send a probe and fold the outcome into the evidence log."""
        try:
            result = self.client.send(probe)
        except BudgetExhausted:
            return None
        self.evidence.add(result)
        return result

    def run(self) -> RunResult:
        started = time.monotonic()
        checkpoints: list[dict[str, Any]] = []

        while self.client.remaining > 0:
            before = self.client.used
            try:
                self.step()
            except BudgetExhausted:
                break
            if self.client.used == before:
                # A step that sends nothing would spin forever.
                break
            if self.client.used % CHECKPOINT_EVERY == 0:
                rules = self.report_contract()
                checkpoints.append({"probes": self.client.used, "rules": rules})
                self.trace.write("checkpoint", probes=self.client.used, rules=rules)

        final = self.report_contract()
        self.trace.write("final_contract", probes=self.client.used, rules=final)

        return RunResult(
            agent=self.name,
            variant=self.variant,
            seed=self.seed,
            reported_contract=final,
            checkpoints=checkpoints,
            probes_used=self.client.used,
            llm_calls=self.llm.calls,
            tokens_in=self.llm.tokens_in,
            tokens_out=self.llm.tokens_out,
            cost_usd=self.llm.cost_usd,
            elapsed_s=time.monotonic() - started,
        )

    def report_contract(self) -> list[dict[str, Any]]:
        user = f"ENDPOINTS: {', '.join(self.endpoints)}\n\n{self.evidence.render()}"
        payload = self.llm.complete_json(REPORT_SYSTEM, user, purpose="report")
        return [r.as_dict() for r in parse_rules(payload.get("rules"))]
