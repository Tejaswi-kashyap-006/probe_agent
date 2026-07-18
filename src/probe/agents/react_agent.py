"""Baseline 2: an LLM told to explore the API.

This is the comparison that matters. It has the same probe budget, the same
endpoints, and the same compacted evidence log as the method; what it lacks is
an explicit hypothesis space and any notion of which probe would be most
informative. It decides what to send next by reasoning about what it has seen.
"""

from __future__ import annotations

from typing import Any

from probe.agents.base import Agent
from probe.client import Probe

SYSTEM = """You are reverse-engineering an undocumented HTTP API by sending requests.

Explore it efficiently. You have a limited number of requests. Work out which
parameters exist, which are required, their types, bounds, allowed values,
formats, dependencies between parameters, pagination behaviour, and which
status code each kind of violation returns.

Do not assume this API follows convention. Caps, page indexing, enum members,
identifier formats and error codes may all differ from what you expect.

How to spend your budget well:
- Never repeat a request listed under OBSERVED. It tells you nothing new.
- Cover every endpoint. Do not spend the budget on one of them.
- A request that succeeds teaches you very little. Deliberately send invalid
  and boundary values to find out where the limits are and what each kind of
  violation returns.
- Vary one thing at a time, so you can tell what caused a response.
- When you find a boundary, probe just either side of it.

Reply with JSON:
{"method":"GET"|"POST","path":"/products","params":{...},"body":{...},
 "note":"one fact you have now established, or empty"}

Use params for query strings and body for POST payloads. Send exactly one
request. For a path with {id}, substitute a concrete value."""


MAX_RETRIES = 2


class ReactAgent(Agent):
    name = "react"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._sent: set[str] = set()

    def step(self) -> None:
        probe, payload = self._choose()
        self._sent.add(probe.key())
        self.observe(probe)

        note = payload.get("note")
        if isinstance(note, str):
            self.evidence.note(note)

    def _choose(self) -> tuple[Probe, dict[str, Any]]:
        """Ask for a probe, re-asking if it repeats one already sent.

        A repeat is refused in tokens rather than in budget. Probes are the
        scarce resource under test, so charging this agent a probe for the
        model's tendency to loop would understate the baseline rather than
        measure it. If it keeps repeating, the repeat is sent and does cost a
        probe: failing to diversify is a real failure.
        """
        nudge = ""
        payload: dict[str, Any] = {}
        for _ in range(MAX_RETRIES + 1):
            user = (
                f"ENDPOINTS: {', '.join(self.endpoints)}\n"
                f"PROBES REMAINING: {self.client.remaining}\n\n"
                f"{self.evidence.render()}\n{nudge}\nWhat is your next request?"
            )
            payload = self.llm.complete_json(SYSTEM, user, purpose="react_step")
            probe = self._to_probe(payload)
            if probe is None:
                nudge = "\nYour last reply was not a valid request. Follow the schema."
                continue
            if probe.key() in self._sent:
                nudge = (
                    f"\nYou already sent {probe.describe()} and it taught you nothing "
                    "new. Send a request you have never sent before."
                )
                continue
            return probe, payload

        # Out of retries: send whatever it last proposed, or fall back.
        probe = self._to_probe(payload) or Probe("GET", "/products")
        return probe, payload

    def _to_probe(self, payload: dict[str, Any]) -> Probe | None:
        method = str(payload.get("method") or "").strip().upper()
        path = str(payload.get("path") or "").strip()
        if method not in ("GET", "POST") or not path.startswith("/"):
            return None

        params = payload.get("params")
        body = payload.get("body")
        params = params if isinstance(params, dict) else {}
        body = body if isinstance(body, dict) else None

        if method == "POST" and body is None:
            body = params or {}
            params = {}
        return Probe(method, path, params=params, body=body)
