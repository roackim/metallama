from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..http_client import shared_client
from .probe import probe_one, _DEFAULT_CONTEXT_LENGTH
from .proxy import proxy
from .reasoning import apply_reasoning
from .registry import effective_reasoning_efforts, get_subserver, get_all_subservers, split_virtual_model

router = APIRouter()

_HEALTH_TIMEOUT = httpx.Timeout(1.0)


# ---------------------------------------------------------------------------
# GET /v1/models
# ---------------------------------------------------------------------------


@router.get("/v1/models")
async def list_models() -> JSONResponse:
    models = []
    async with shared_client() as client:
        for srv in get_all_subservers():
            try:
                resp = await client.get(f"{srv.url}/health", timeout=_HEALTH_TIMEOUT)
                if resp.status_code != 200:
                    continue
            except (httpx.ConnectError, httpx.TimeoutException):
                continue
            # Server is up but probe may have missed it at startup — re-probe lazily
            # if it has never successfully returned an upstream model id.
            if srv.context_length == _DEFAULT_CONTEXT_LENGTH or not srv.upstream_model_id:
                await probe_one(srv, client)
            model_name = srv.name
            base_entry = {
                "id": model_name,
                "object": "model",
                "created": 1704067200,
                "owned_by": "metallama",
                "meta": {
                    **srv.upstream_meta,
                    "n_ctx": srv.context_length,
                    "vision": srv.vision,
                },
                "context_length": srv.context_length,
            }
            # Virtual reasoning-effort models (e.g. "name:low", "name:high"),
            # derived from the server's effective (enabled ∩ supported) efforts.
            effective_efforts = effective_reasoning_efforts(srv)
            if not effective_efforts:
                models.append(base_entry)
            for effort in effective_efforts:
                vname = f"{model_name}:{effort}"
                models.append({**base_entry, "id": vname})
    return JSONResponse({"object": "list", "data": models})


# ---------------------------------------------------------------------------
# POST /v1/chat/completions — passthrough
# ---------------------------------------------------------------------------


@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: Request) -> Response:
    body: dict[str, Any] = await request.json()
    model = body.get("model", "")
    srv = get_subserver(model)
    # Strip any virtual reasoning-effort suffix, map effort / preserve_thinking
    # into chat_template_kwargs, and normalize past thinking in the history.
    body["model"], _ = split_virtual_model(model)
    apply_reasoning(body, body, model)
    return await proxy("POST", f"{srv.url}/v1/chat/completions", json_body=body)


# ---------------------------------------------------------------------------
# POST /v1/completions — passthrough
# ---------------------------------------------------------------------------


@router.post("/v1/completions", response_model=None)
async def completions(request: Request) -> Response:
    body: dict[str, Any] = await request.json()
    srv = get_subserver(body.get("model", ""))
    return await proxy("POST", f"{srv.url}/v1/completions", json_body=body)


# ---------------------------------------------------------------------------
# POST /v1/embeddings — passthrough
# ---------------------------------------------------------------------------


@router.post("/v1/embeddings", response_model=None)
async def embeddings(request: Request) -> Response:
    body: dict[str, Any] = await request.json()
    srv = get_subserver(body.get("model", ""))
    return await proxy("POST", f"{srv.url}/v1/embeddings", json_body=body)
