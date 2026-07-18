"""Run agents and score them.

Ground truth arrives as data, never as an import: this module sits inside the
agent package and must not be able to reach the contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from probe.agents.base import Agent, RunResult
from probe.agents.random_agent import RandomAgent
from probe.agents.react_agent import ReactAgent
from probe.client import ProbeClient
from probe.config import Config
from probe.eval.scoring import score_by_subset
from probe.llm import LLMClient
from probe.trace import Trace

AGENTS: dict[str, type[Agent]] = {
    "random": RandomAgent,
    "react": ReactAgent,
}

ENDPOINTS = ("GET /products", "POST /orders", "GET /orders/{id}")


def run_one(
    agent_name: str,
    truth: list[dict[str, Any]],
    achievable: set[str],
    config: Config,
    trace_dir: Path,
) -> dict[str, Any]:
    """One agent, one variant, one seed. Returns the scored summary."""
    trace_path = trace_dir / f"{agent_name}_{config.variant}_seed{config.seed}.jsonl"
    trace = Trace(
        trace_path,
        {
            "agent": agent_name,
            "variant": config.variant,
            "seed": config.seed,
            "budget": config.probe_budget,
            "model": config.model,
        },
    )
    client = ProbeClient(config.base_url, budget=config.probe_budget, trace=trace)
    llm = LLMClient(
        model=config.model,
        max_prompt_tokens=config.max_prompt_tokens,
        max_calls=config.max_llm_calls,
        seed=config.seed,
        trace=trace,
    )

    agent = AGENTS[agent_name](
        client=client,
        llm=llm,
        trace=trace,
        endpoints=ENDPOINTS,
        variant=config.variant,
        seed=config.seed,
    )

    try:
        result = agent.run()
    finally:
        client.close()

    summary = summarize(result, truth, achievable)
    trace.write("score", **summary["score"])
    trace.close()
    summary["trace"] = str(trace_path)
    return summary


def summarize(
    result: RunResult,
    truth: list[dict[str, Any]],
    achievable: set[str],
) -> dict[str, Any]:
    """Final score plus the recovery curve across checkpoints."""
    final = score_by_subset(result.reported_contract, truth, achievable)

    curve = [
        {
            "probes": cp["probes"],
            **{
                "recall": score_by_subset(cp["rules"], truth, achievable)["all"]["recall"],
                "f1": score_by_subset(cp["rules"], truth, achievable)["all"]["f1"],
            },
        }
        for cp in result.checkpoints
    ]

    target = next((c["probes"] for c in curve if c["recall"] >= 0.8), None)

    return {
        "agent": result.agent,
        "variant": result.variant,
        "seed": result.seed,
        "probes_used": result.probes_used,
        "llm_calls": result.llm_calls,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "cost_usd": round(result.cost_usd, 6),
        "elapsed_s": round(result.elapsed_s, 2),
        "score": final,
        "recovery_curve": curve,
        "probes_to_80pct_recall": target,
        "reported_contract": result.reported_contract,
    }


def write_summary(summaries: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
