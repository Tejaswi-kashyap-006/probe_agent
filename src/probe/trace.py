"""Structured JSONL trace. Every figure is rebuilt from these files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Trace:
    """Append-only JSONL writer. One file per run."""

    def __init__(self, path: Path, meta: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = path.open("w", encoding="utf-8")
        self.write("meta", **meta)

    def write(self, kind: str, **payload: Any) -> None:
        record = {"kind": kind, **payload}
        self._fh.write(json.dumps(record, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> Trace:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read(path: Path) -> list[dict[str, Any]]:
    """Load a trace back as a list of records."""
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
