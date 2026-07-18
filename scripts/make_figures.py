"""Rebuild every figure from the traces on disk.

If a figure cannot be produced by running this against the JSONL, it is not
done. Nothing here carries data of its own.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from probe.config import REPO_ROOT as ROOT  # noqa: E402
from probe.config import TRACE_DIR  # noqa: E402
from probe.viz import declassify, partition, recovery_curve, swarm, tape  # noqa: E402
from probe.viz.trace_export import load_all  # noqa: E402
from target_api.contract import rule_as_dict  # noqa: E402
from target_api.variants import VARIANTS  # noqa: E402

ORDER = {"random": 0, "react": 1, "hypothesis": 2, "eig": 3}


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild figures from traces")
    parser.add_argument("--variant", default="easy")
    parser.add_argument("--traces", default=str(TRACE_DIR))
    parser.add_argument("--out", default=str(ROOT / "figures"))
    args = parser.parse_args()

    trace_dir, out_dir = Path(args.traces), Path(args.out)
    views = load_all(trace_dir, variant=args.variant)
    if not views:
        raise SystemExit(f"no traces for variant {args.variant!r} in {trace_dir}")

    views.sort(key=lambda v: ORDER.get(v.agent, 99))
    truth = [rule_as_dict(r) for r in VARIANTS[args.variant].rules]
    budget = int(views[0].meta.get("budget", 100))
    written: list[Path] = []

    def note(path: Path | None) -> None:
        if path is not None:
            written.append(path)

    note(declassify.render(views, truth, out_dir / f"declassify_{args.variant}.html", budget))

    eig_view = next((v for v in views if v.agent == "eig"), None)
    if eig_view is not None:
        note(swarm.render(eig_view, out_dir / f"swarm_{args.variant}.html"))
        note(partition.render(eig_view, out_dir / f"partition_{args.variant}.svg"))

    note(tape.render(views, out_dir / f"tape_{args.variant}.svg"))
    note(recovery_curve.render(views, out_dir / f"recovery_{args.variant}.svg"))

    for path in written:
        print(f"wrote {path}")
    if not written:
        print("nothing written: traces contain no figure-bearing events")


if __name__ == "__main__":
    main()
