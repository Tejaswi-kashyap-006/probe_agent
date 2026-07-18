"""Compact evidence log.

Prompts carry distilled facts, never the raw transcript. Appending every
request and response would grow tokens quadratically with probe count and bury
the signal in noise; raw responses live in the trace on disk instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from probe.client import ProbeResult

# Large enough that an agent working through a 100-probe budget can still see
# everything it has already sent. Forgetting drives agents into repeat loops,
# which would understate a baseline rather than measure it.
MAX_OBSERVATIONS = 80
RECENT = 5


@dataclass
class Evidence:
    """Deduplicated observations plus whatever the model has concluded."""

    observations: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    recent: list[str] = field(default_factory=list)

    def add(self, result: ProbeResult) -> None:
        # Keying on the request deduplicates repeats by construction.
        self.observations[result.probe.describe()] = self._outcome(result)
        self.recent.append(result.describe())
        del self.recent[:-RECENT]

    @staticmethod
    def _outcome(result: ProbeResult) -> str:
        bits = [str(result.status)]
        if result.error:
            bits.append(result.error)
        if result.fields:
            bits.append(f"fields={list(result.fields)}")
        if result.status == 200 and "count" in result.body:
            bits.append(f"count={result.body['count']}")
        return " ".join(bits)

    def note(self, text: str) -> None:
        text = text.strip()
        if text and text not in self.notes:
            self.notes.append(text)
            del self.notes[:-20]

    def ask(self, text: str) -> None:
        text = text.strip()
        if text and text not in self.open_questions:
            self.open_questions.append(text)
            del self.open_questions[:-10]

    def render(self) -> str:
        """Bounded rendering. Keeps the newest observations when it overflows."""
        items = list(self.observations.items())
        omitted = max(0, len(items) - MAX_OBSERVATIONS)
        shown = items[-MAX_OBSERVATIONS:]

        lines = ["OBSERVED (request -> outcome):"]
        if omitted:
            lines.append(f"  ... {omitted} older observations distilled away")
        lines += [f"  {req} -> {out}" for req, out in shown]

        if self.notes:
            lines.append("CONFIRMED:")
            lines += [f"  {n}" for n in self.notes]
        if self.open_questions:
            lines.append("OPEN QUESTIONS:")
            lines += [f"  {q}" for q in self.open_questions]
        return "\n".join(lines)
