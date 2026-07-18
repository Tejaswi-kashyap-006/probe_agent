"""Run experiments.

The harness may see the ground truth; the agent may not. This script imports it
and hands it to the scorer as data.

Defaults to a smoke config. The full matrix is opt-in via --full.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from probe.config import ARTIFACT_DIR, TRACE_DIR, Config  # noqa: E402
from probe.eval.runner import AGENTS, run_one, write_summary  # noqa: E402
from target_api.contract import rule_as_dict  # noqa: E402
from target_api.variants import VARIANTS  # noqa: E402


def start_server(variant: str) -> tuple[str, Any]:
    """Serve one variant on an ephemeral port for the duration of a run."""
    import os

    import uvicorn

    os.environ["PROBE_VARIANT"] = variant
    for module in [m for m in list(sys.modules) if m.startswith("target_api.server")]:
        del sys.modules[module]
    from target_api.server import app

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError(f"target API for variant {variant} did not start")
        time.sleep(0.01)

    port = server.servers[0].sockets[0].getsockname()[1]
    return f"http://127.0.0.1:{port}", server


def load_achievable(variant: str) -> set[str]:
    path = ARTIFACT_DIR / f"identifiability_{variant}.json"
    if not path.exists():
        raise SystemExit(
            f"missing {path}. Run: python -m target_api.identifiability"
        )
    return set(json.loads(path.read_text(encoding="utf-8"))["achievable_rules"])


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")

    parser = argparse.ArgumentParser(description="Run probe experiments")
    parser.add_argument("--agent", action="append", choices=sorted(AGENTS))
    parser.add_argument("--variant", action="append", choices=sorted(VARIANTS))
    parser.add_argument("--seed", action="append", type=int)
    parser.add_argument("--budget", type=int, default=100)
    parser.add_argument("--full", action="store_true", help="the whole matrix")
    parser.add_argument("--out", default=str(TRACE_DIR / "summary.json"))
    args = parser.parse_args()

    if args.full:
        agents = sorted(AGENTS)
        variants = sorted(VARIANTS)
        seeds = [0, 1, 2]
    else:
        agents = args.agent or ["random", "react"]
        variants = args.variant or ["easy"]
        seeds = args.seed or [0]

    runs = list(itertools.product(agents, variants, seeds))
    print(f"{len(runs)} run(s): agents={agents} variants={variants} seeds={seeds} "
          f"budget={args.budget}")

    summaries: list[dict[str, Any]] = []
    total_calls = 0
    total_cost = 0.0

    for variant in variants:
        truth = [rule_as_dict(r) for r in VARIANTS[variant].rules]
        achievable = load_achievable(variant)
        base_url, server = start_server(variant)
        try:
            for agent_name, run_variant, seed in runs:
                if run_variant != variant:
                    continue
                config = Config(
                    base_url=base_url,
                    variant=variant,
                    probe_budget=args.budget,
                    seed=seed,
                )
                summary = run_one(agent_name, truth, achievable, config, TRACE_DIR)
                summaries.append(summary)

                total_calls += summary["llm_calls"]
                total_cost += summary["cost_usd"]
                subsets = summary["score"]
                print(
                    f"  {agent_name:<10} {variant:<7} seed={seed}  "
                    f"F1={subsets['all']['f1']:.3f}  "
                    f"conv={subsets.get('conventional', {}).get('recall', 0):.3f}  "
                    f"cp={subsets.get('counter_prior', {}).get('recall', 0):.3f}  "
                    f"probes={summary['probes_used']}  "
                    f"llm={summary['llm_calls']}  "
                    f"${summary['cost_usd']:.4f}  "
                    f"[cumulative: {total_calls} calls, ${total_cost:.3f}]"
                )
        finally:
            server.should_exit = True
            time.sleep(0.3)

    write_summary(summaries, Path(args.out))
    print(f"\ntotal: {total_calls} LLM calls, ${total_cost:.3f}")
    print(f"summary -> {args.out}")


if __name__ == "__main__":
    main()
