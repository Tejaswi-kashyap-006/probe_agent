"""Turn a JSONL trace into the shape the figures want.

Every figure reads from here. Nothing is ever typed into a visual by hand: a
figure that cannot be rebuilt by re-running against the trace does not ship.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probe.trace import read


@dataclass
class RunView:
    meta: dict[str, Any] = field(default_factory=dict)
    probes: list[dict[str, Any]] = field(default_factory=list)
    eig_steps: list[dict[str, Any]] = field(default_factory=list)
    deaths: list[dict[str, Any]] = field(default_factory=list)
    reproposals: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    final_rules: list[dict[str, Any]] = field(default_factory=list)
    score: dict[str, Any] = field(default_factory=dict)
    llm_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def agent(self) -> str:
        return str(self.meta.get("agent", "?"))

    @property
    def variant(self) -> str:
        return str(self.meta.get("variant", "?"))

    def eig_by_probe(self) -> list[float]:
        """One information-gain value per probe, zero where nothing was scored.

        The baselines never compute EIG, so their tape is scored the same way
        every other agent's is: against the frozen referee, not against beliefs
        they never held.
        """
        series = [0.0] * len(self.probes)
        for i, step in enumerate(self.eig_steps):
            if i < len(series):
                series[i] = float(step.get("eig", 0.0))
        return series


def load(path: Path) -> RunView:
    view = RunView()
    for record in read(path):
        kind = record.pop("kind", "")
        if kind == "meta":
            view.meta = record
        elif kind == "probe":
            view.probes.append(record)
        elif kind == "eig":
            view.eig_steps.append(record)
        elif kind == "hypothesis_death":
            view.deaths.append(record)
        elif kind == "reproposal":
            view.reproposals.append(record)
        elif kind == "checkpoint_score":
            view.checkpoints.append(record)
        elif kind == "final_contract":
            view.final_rules = record.get("rules", [])
        elif kind == "score":
            view.score = record
        elif kind == "llm_call":
            view.llm_calls.append(record)
    return view


def load_all(trace_dir: Path, variant: str | None = None) -> list[RunView]:
    views = [load(p) for p in sorted(trace_dir.glob("*.jsonl"))]
    return [v for v in views if variant is None or v.variant == variant]


def first_confirmed_at(
    view: RunView, truth_ids: list[str]
) -> dict[str, int | None]:
    """The probe index at which each true rule first appears and stays correct.

    Drives the reveal schedule of the declassification race. A rule that is
    claimed and later retracted is credited from the checkpoint it first
    survived to the end, not from the moment it was first guessed.
    """
    schedule: dict[str, int | None] = {rule_id: None for rule_id in truth_ids}
    for checkpoint in view.checkpoints:
        matched = checkpoint.get("matched_rule_ids") or []
        for rule_id in matched:
            if rule_id in schedule and schedule[rule_id] is None:
                schedule[rule_id] = int(checkpoint.get("probes", 0))
    return schedule
