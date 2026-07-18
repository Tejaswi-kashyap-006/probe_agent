"""HTTP probe client: the agent's only channel to the API.

Counts every probe against the budget, caches identical requests, and logs each
one to the trace. A cached repeat still costs budget: in the real world you
would have sent it, and not charging for it would flatter agents that repeat
themselves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from probe.trace import Trace


class BudgetExhausted(RuntimeError):
    """Raised when an agent tries to probe past its budget."""


@dataclass(frozen=True)
class Probe:
    method: str
    path: str
    params: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] | None = None

    def key(self) -> str:
        return json.dumps(
            {"m": self.method, "p": self.path, "q": self.params, "b": self.body},
            sort_keys=True,
            default=str,
        )

    def describe(self) -> str:
        if self.body is not None:
            return f"{self.method} {self.path} {json.dumps(self.body, sort_keys=True)}"
        if self.params:
            return f"{self.method} {self.path}?{json.dumps(self.params, sort_keys=True)}"
        return f"{self.method} {self.path}"


@dataclass(frozen=True)
class ProbeResult:
    index: int
    probe: Probe
    status: int
    body: dict[str, Any]
    error: str | None
    fields: tuple[str, ...]
    cached: bool

    def describe(self) -> str:
        """Compact one-line rendering for prompts."""
        bits = [f"-> {self.status}"]
        if self.error:
            bits.append(self.error)
        if self.fields:
            bits.append(f"fields={list(self.fields)}")
        if self.status == 200 and "count" in self.body:
            bits.append(f"count={self.body['count']}")
        return f"{self.probe.describe()} {' '.join(bits)}"


class ProbeClient:
    """Budget-enforcing, caching HTTP client."""

    def __init__(
        self,
        base_url: str,
        budget: int,
        trace: Trace | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)
        self.budget = budget
        self.used = 0
        self._cache: dict[str, tuple[int, dict[str, Any]]] = {}
        self._trace = trace

    @property
    def remaining(self) -> int:
        return self.budget - self.used

    def send(self, probe: Probe) -> ProbeResult:
        if self.used >= self.budget:
            raise BudgetExhausted(f"probe budget of {self.budget} exhausted")

        key = probe.key()
        cached = key in self._cache
        if cached:
            status, payload = self._cache[key]
        else:
            response = self._client.request(
                probe.method,
                probe.path,
                params=probe.params or None,
                json=probe.body,
            )
            status = response.status_code
            try:
                payload = response.json()
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            self._cache[key] = (status, payload)

        self.used += 1
        result = ProbeResult(
            index=self.used,
            probe=probe,
            status=status,
            body=payload.get("body", {}) or {},
            error=payload.get("error"),
            fields=tuple(payload.get("fields", []) or []),
            cached=cached,
        )

        if self._trace is not None:
            self._trace.write(
                "probe",
                index=result.index,
                method=probe.method,
                path=probe.path,
                params=probe.params,
                body=probe.body,
                status=result.status,
                error=result.error,
                fields=list(result.fields),
                response_body=result.body,
                cached=cached,
            )
        return result

    def close(self) -> None:
        self._client.close()
