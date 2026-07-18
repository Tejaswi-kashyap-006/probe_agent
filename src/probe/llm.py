"""LLM calls: hard token ceiling, token counting, disk cache, cost estimate.

The token ceiling is enforced here rather than trusted to prompt construction.
A prompt that grows past the limit means the evidence log stopped being
compacted, which is a bug: it fails loudly instead of silently costing money.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import tiktoken
from openai import OpenAI

from probe.config import CACHE_DIR, MODEL, PRICE_IN, PRICE_OUT
from probe.trace import Trace


class TokenCeilingExceeded(RuntimeError):
    """A prompt exceeded the configured input-token ceiling."""


class CallBudgetExceeded(RuntimeError):
    """A single run made more LLM calls than any sane trajectory needs."""


def _encoding(model: str) -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("o200k_base")


class LLMClient:
    def __init__(
        self,
        model: str = MODEL,
        max_prompt_tokens: int = 6000,
        max_calls: int = 300,
        seed: int = 0,
        trace: Trace | None = None,
        cache_dir: Path = CACHE_DIR / "llm",
    ) -> None:
        self.model = model
        self.max_prompt_tokens = max_prompt_tokens
        self.max_calls = max_calls
        self.seed = seed
        self._trace = trace
        self._enc = _encoding(model)
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._client: OpenAI | None = None

        self.calls = 0
        self.cached_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0

    @property
    def cost_usd(self) -> float:
        return (self.tokens_in * PRICE_IN + self.tokens_out * PRICE_OUT) / 1_000_000

    def count_tokens(self, text: str) -> int:
        return len(self._enc.encode(text))

    def _lazy_client(self) -> OpenAI:
        if self._client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise RuntimeError("OPENAI_API_KEY is not set")
            self._client = OpenAI()
        return self._client

    def complete_json(self, system: str, user: str, purpose: str = "") -> dict[str, Any]:
        """One JSON-mode completion. Returns {} if the model emits invalid JSON."""
        prompt_tokens = self.count_tokens(system) + self.count_tokens(user)
        if prompt_tokens > self.max_prompt_tokens:
            raise TokenCeilingExceeded(
                f"prompt is {prompt_tokens} tokens, ceiling is {self.max_prompt_tokens} "
                f"(purpose={purpose!r}); the evidence log is not being compacted"
            )
        if self.calls >= self.max_calls:
            raise CallBudgetExceeded(
                f"{self.calls} LLM calls in one run; something is looping"
            )

        digest = hashlib.sha256(
            json.dumps([self.model, system, user, self.seed], sort_keys=True).encode()
        ).hexdigest()
        cache_file = self._cache_dir / f"{digest}.json"

        if cache_file.exists():
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            self.cached_calls += 1
            self._log(purpose, prompt_tokens, 0, True)
            return payload["parsed"]

        response = self._lazy_client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=1.0,
            seed=self.seed,
        )
        text = response.choices[0].message.content or "{}"
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}

        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else prompt_tokens
        tokens_out = usage.completion_tokens if usage else 0
        self.calls += 1
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out

        cache_file.write_text(json.dumps({"parsed": parsed}), encoding="utf-8")
        self._log(purpose, tokens_in, tokens_out, False)
        return parsed

    def _log(self, purpose: str, tokens_in: int, tokens_out: int, cached: bool) -> None:
        if self._trace is not None:
            self._trace.write(
                "llm_call",
                purpose=purpose,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cached=cached,
                cumulative_calls=self.calls,
                cumulative_cost_usd=round(self.cost_usd, 6),
            )
