"""Start the target API. Usage: python scripts/serve.py [--variant easy] [--port 8000]."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# target_api is deliberately not an installed package, so the agent cannot
# import it; the repo root has to go on sys.path by hand.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the target API")
    parser.add_argument("--variant", default="easy")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    os.environ["PROBE_VARIANT"] = args.variant

    import uvicorn

    print(f"serving variant={args.variant} on http://{args.host}:{args.port}")
    uvicorn.run("target_api.server:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
