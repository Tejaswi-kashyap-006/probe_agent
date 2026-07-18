"""LLM proposal of candidate probes.

This is the equivalence oracle approximation. No black-box setting offers a
real one, so it is replaced by conformance testing: generating the inputs where
the current model of the world is most likely to be wrong. A classical learner
has to enumerate; a language model has priors about how APIs behave and can go
straight to the suspicious cases.

The model proposes and information theory disposes: these candidates are only
suggestions, and the probe actually sent is whichever one splits the hypotheses
most evenly.
"""

from __future__ import annotations

from typing import Any

from probe.client import Probe
from probe.hypothesis.space import Factor
from probe.llm import LLMClient

SYSTEM = """You are choosing candidate HTTP requests that would discriminate between
competing hypotheses about an undocumented API.

You are given several hypotheses that disagree about one aspect of the API.
Propose requests whose response would differ depending on which hypothesis is
true. Boundary values are especially useful: if hypotheses disagree about a
limit, probe just either side of it.

Vary only the aspect in question. Keep everything else at known-valid values so
the response has an unambiguous cause.

Never propose a request that appears in ALREADY SENT.

Reply with JSON:
{"probes":[{"method":"GET","path":"/products","params":{...},"body":{...}}, ...]}"""


def propose_probes(
    llm: LLMClient,
    factor: Factor,
    evidence: str,
    already_sent: list[str],
    k: int,
) -> list[Probe]:
    """Candidate probes aimed at one factor's disagreement."""
    hypotheses = "\n".join(
        f"  H{i}: {[r.as_dict() for r in p.rules] or 'no constraint'}"
        for i, p in enumerate(factor.particles[:8])
    )
    recent_sent = already_sent[-40:]
    user = (
        f"ENDPOINT: {factor.endpoint}\n"
        f"COMPETING HYPOTHESES:\n{hypotheses}\n\n"
        f"{evidence}\n\n"
        f"ALREADY SENT:\n" + "\n".join(f"  {s}" for s in recent_sent) + "\n\n"
        f"Propose {k} discriminating requests."
    )
    payload = llm.complete_json(SYSTEM, user, purpose="candidates")
    return [p for p in (_to_probe(raw) for raw in payload.get("probes", []) or []) if p]


def _to_probe(raw: Any) -> Probe | None:
    if not isinstance(raw, dict):
        return None
    method = str(raw.get("method") or "").strip().upper()
    path = str(raw.get("path") or "").strip()
    if method not in ("GET", "POST") or not path.startswith("/"):
        return None

    params = raw.get("params")
    body = raw.get("body")
    params = params if isinstance(params, dict) else {}
    body = body if isinstance(body, dict) else None
    if method == "POST" and body is None:
        body, params = params or {}, {}
    return Probe(method, path, params=params, body=body)
