"""FastAPI wrapper around the ground-truth contract.

All contract logic lives in contract.py; this module only translates HTTP to
native-typed params and back. Deterministic, stateless, and it never leaks the
spec: no /docs, no /redoc, no /openapi.json, and error bodies carry only what
the variant's verbosity allows.
"""

from __future__ import annotations

import os
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from target_api.contract import evaluate
from target_api.variants import VARIANTS

VARIANT_NAME = os.environ.get("PROBE_VARIANT", "easy")
if VARIANT_NAME not in VARIANTS:
    raise SystemExit(f"unknown PROBE_VARIANT {VARIANT_NAME!r}; have {sorted(VARIANTS)}")
CONTRACT = VARIANTS[VARIANT_NAME]

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _coerce(raw: str) -> Any:
    """Query strings are untyped; recover ints so type rules stay meaningful."""
    return int(raw) if re.fullmatch(r"-?\d+", raw) else raw


def _respond(endpoint: str, params: dict[str, Any]) -> JSONResponse:
    outcome = evaluate(CONTRACT, endpoint, params)
    return JSONResponse(
        status_code=outcome.status,
        content=outcome.project(CONTRACT.verbosity),
    )


@app.get("/products")
async def get_products(request: Request) -> JSONResponse:
    params = {k: _coerce(v) for k, v in request.query_params.items()}
    return _respond("GET /products", params)


@app.post("/orders")
async def post_orders(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"status": 400})
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"status": 400})
    return _respond("POST /orders", body)


@app.get("/orders/{order_id}")
async def get_order(order_id: str) -> JSONResponse:
    return _respond("GET /orders/{id}", {"id": order_id})


@app.post("/__admin/reset")
async def reset() -> dict[str, str]:
    """Harness-only. The server is stateless, so this is a no-op acknowledgement."""
    return {"status": "ok", "variant": CONTRACT.name}
