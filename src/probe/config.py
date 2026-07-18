"""Run configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACE_DIR = REPO_ROOT / "traces"
CACHE_DIR = REPO_ROOT / ".cache"
ARTIFACT_DIR = REPO_ROOT / "artifacts"

MODEL = "gpt-4o-mini"

# gpt-4o-mini list price, USD per million tokens.
PRICE_IN = 0.15
PRICE_OUT = 0.60


@dataclass(frozen=True)
class Config:
    base_url: str = "http://127.0.0.1:8000"
    variant: str = "easy"
    probe_budget: int = 100
    seed: int = 0
    model: str = MODEL
    # Exceeding this is a bug, not a cost of doing business.
    max_prompt_tokens: int = 6000
    # A run that needs this many LLM calls is looping.
    max_llm_calls: int = 300
    hypotheses_per_factor: int = 12
    diversity_floor: int = 8
    candidate_probes: int = 12
