"""Shared fixtures. Tests may reach the ground truth; agent code may not."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

from target_api.server import app


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    """A real server on an ephemeral port, so probes go over real HTTP."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("target API did not start")
        time.sleep(0.01)

    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)
