"""Native llama.cpp API, mounted at /llamacpp, shaped like llama-server's router mode.

One base URL serves every model, the way `llama-server --models-dir` does:

- POST requests are routed by the JSON body's `model` field.
- GET requests (e.g. /props, /slots) take `?model=<name>`.
- GET /models and /v1/models list every model with its load status.
- POST /models/load and /models/unload start / stop managed servers.

Requests are forwarded to the backing llama-server unchanged, except that the
`model` value is rewritten to the upstream id, and chat completions get the
gateway's reasoning controls (virtual `:effort` suffix, preserve_thinking, ...).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from ..auth import admin_guard
from ..http_client import shared_client
from ..profiles import MODEL_PROFILES
from ..runtime import status_for
from .openai import _reasoning_fields
from .probe import probe_one
from .proxy import proxy
from .reasoning import apply_reasoning
from .registry import (
    effective_reasoning_efforts, get_all_subservers, get_subserver, split_virtual_model, virtual_efforts,
)
from .schemas import SubserverConfig

router = APIRouter()

_CHAT_PATHS = {"v1/chat/completions", "chat/completions"}

# Request headers worth forwarding upstream (llama-server may run with --api-key).
_FORWARD_HEADERS = ("content-type", "accept", "authorization")

_HEALTH_TIMEOUT = httpx.Timeout(1.0)

# metallama runtime status → llama-server router status
_STATUS_MAP = {"online": "loaded", "starting": "loading", "offline": "unloaded"}


def _error(message: str, status_code: int) -> JSONResponse:
    """llama-server's error shape."""
    kind = "not_found_error" if status_code == 404 else "invalid_request_error"
    return JSONResponse(
        {"error": {"code": status_code, "message": message, "type": kind}}, status_code=status_code,
    )


async def _status(srv: SubserverConfig, client: httpx.AsyncClient) -> str:
    profile = MODEL_PROFILES.get(srv.name)
    if profile is not None:
        return _STATUS_MAP.get(await status_for(profile), "unloaded")
    try:
        resp = await client.get(f"{srv.url}/health", timeout=_HEALTH_TIMEOUT)
        return "loaded" if resp.status_code == 200 else "loading"
    except httpx.HTTPError:
        return "unloaded"


# ---------------------------------------------------------------------------
# Model list + load / unload (router API)
# ---------------------------------------------------------------------------


@router.get("/models")
@router.get("/v1/models")
async def list_models() -> JSONResponse:
    models = []
    async with shared_client() as client:
        for srv in get_all_subservers():
            status = await _status(srv, client)
            # Backfill metadata (vision, context, efforts) for a server that came
            # up after startup, as /openai/v1/models does.
            if status == "loaded" and (not srv.vision_known or not srv.upstream_model_id):
                await probe_one(srv, client)
            entry = {
                "id": srv.name,
                "object": "model",
                "owned_by": "metallama",
                "created": 1704067200,
                "status": {"value": status},
                "meta": {**srv.upstream_meta, "n_ctx": srv.context_length},
                # Extensions beyond llama-server, same shape as /openai/v1/models.
                "context_length": srv.context_length,
                # Omitted while vision is unknown: absence means "unknown".
                **({"architecture": {
                    "input_modalities": ["text", "image"] if srv.vision else ["text"],
                    "output_modalities": ["text"],
                }} if srv.vision_known else {}),
                **_reasoning_fields(effective_reasoning_efforts(srv), srv.default_reasoning_effort),
            }
            models.append(entry)
            # Same virtual "name:effort" models as the other gateways.
            for effort in virtual_efforts(srv):
                models.append({**entry, "id": f"{srv.name}:{effort}"})
    return JSONResponse({"object": "list", "data": models})


async def _load_or_unload(body: dict[str, Any], start: bool) -> JSONResponse:
    # main imports this router, so resolve the lifecycle handlers lazily.
    from ..main import start_model, stop_model

    name, _ = split_virtual_model(str(body.get("model", "")))
    if not name:
        return _error("model is required", 400)
    if name not in MODEL_PROFILES:
        known = any(srv.name == name for srv in get_all_subservers())
        return _error("remote models cannot be loaded or unloaded" if known else "model not found", 400 if known else 404)
    if start and await status_for(MODEL_PROFILES[name]) != "offline":
        return JSONResponse({"success": True})
    try:
        await (start_model if start else stop_model)(name, None)
    except HTTPException as exc:
        return _error(str(exc.detail), exc.status_code)
    return JSONResponse({"success": True})


async def _json_body(request: Request) -> dict[str, Any]:
    """Parse the body as JSON whatever the content type, like llama-server (curl -d sends form-urlencoded)."""
    try:
        parsed = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


@router.post("/models/load")
async def load_model(request: Request, _guard: None = Depends(admin_guard)) -> JSONResponse:
    return await _load_or_unload(await _json_body(request), start=True)


@router.post("/models/unload")
async def unload_model(request: Request, _guard: None = Depends(admin_guard)) -> JSONResponse:
    return await _load_or_unload(await _json_body(request), start=False)


@router.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Everything else: route by model and forward
# ---------------------------------------------------------------------------


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], response_model=None, include_in_schema=False)
async def passthrough(path: str, request: Request) -> Response:
    headers = {k: v for k in _FORWARD_HEADERS if (v := request.headers.get(k))}
    content = await request.body()
    params = dict(request.query_params)

    body: dict[str, Any] | None = None
    # llama-server parses bodies as JSON whatever the content type (curl defaults
    # to form-urlencoded), so do the same; only multipart uploads are left raw.
    if content and "multipart/" not in headers.get("content-type", ""):
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed = None  # not JSON: forward untouched, upstream decides
        if isinstance(parsed, dict):
            body = parsed

    # Router semantics: body `model` for POSTs, `?model=` otherwise. A lone
    # backend needs no selector, like a single-model llama-server.
    model = (body or {}).get("model") or params.get("model")
    if not model:
        servers = get_all_subservers()
        if len(servers) != 1:
            return _error("model is required: set `model` in the body or `?model=`", 400)
        model = servers[0].name
    try:
        srv = get_subserver(str(model))
    except HTTPException:
        return _error(f"model not found: {model}", 404)

    upstream_model = srv.upstream_model_id or srv.name
    if "model" in params:
        params["model"] = upstream_model
    if body is not None:
        if path.strip("/") in _CHAT_PATHS:
            try:
                apply_reasoning(body, srv, str(model), dict(body))
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
                return _error(str(detail.get("error")), exc.status_code)
        if "model" in body:
            body["model"] = upstream_model
        content = json.dumps(body).encode()
        headers["content-type"] = "application/json"

    return await proxy(request.method, f"{srv.url}/{path}", content=content or None, params=params, headers=headers)
