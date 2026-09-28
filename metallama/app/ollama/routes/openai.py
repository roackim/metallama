"""OpenAI-compatible gateway, mounted at /openai (and at /ollama for legacy clients).

A thin router over llama-server's own OpenAI API: it picks the upstream from
the model name, strips any virtual "name:effort" suffix, validates the
reasoning effort, and forwards the body and the response unchanged.
"""
from __future__ import annotations

from typing import Any, Callable

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from ...http_client import get_client, shared_client
from ..probe import probe_one, _DEFAULT_CONTEXT_LENGTH
from ..schemas import SubserverConfig
from ..registry import (
    effective_reasoning_efforts,
    get_all_subservers,
    get_subserver,
    split_virtual_model,
    virtual_efforts,
)
from .ollama import _apply_reasoning_effort

router = APIRouter()

_TIMEOUT = httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0)
_HEALTH_TIMEOUT = httpx.Timeout(1.0)


# ---------------------------------------------------------------------------
# GET /v1/models
# ---------------------------------------------------------------------------


def _reasoning_fields(allowed_efforts: list[str], default_effort: str | None) -> dict[str, Any]:
    """OpenRouter-style reasoning advertisement for a /models entry.

    Mirrors openrouter.ai/api/v1/models: `supported_parameters` plus a
    `reasoning` object listing the exact efforts a request may send. Empty
    when the server allows none. Keys without a value are omitted, never
    null (clients may store entries as TOML).
    """
    if not allowed_efforts:
        return {}
    reasoning: dict[str, Any] = {
        "mandatory": "none" not in allowed_efforts,
        "default_enabled": True,
        "supported_efforts": allowed_efforts,
    }
    # Only advertise a default a client could send back without a 400.
    if default_effort in allowed_efforts:
        reasoning["default_effort"] = default_effort
    return {
        "supported_parameters": ["include_reasoning", "reasoning", "reasoning_effort"],
        "reasoning": reasoning,
    }


async def healthy_subservers() -> list[SubserverConfig]:
    """Servers whose /health answers, probed lazily if never probed before."""
    healthy = []
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
            healthy.append(srv)
    return healthy


@router.get("/v1/models")
async def list_models() -> JSONResponse:
    models = []
    for srv in await healthy_subservers():
        model_name = srv.name
        allowed_efforts = effective_reasoning_efforts(srv)
        base_entry = {
            "id": model_name,
            "object": "model",
            "created": 1704067200,
            "owned_by": "metallama",
            "meta": {
                **srv.upstream_meta,
                "n_ctx": srv.context_length,
                "vision": srv.vision,
                "reasoning_efforts": allowed_efforts,
            },
            "context_length": srv.context_length,
            **_reasoning_fields(allowed_efforts, srv.default_reasoning_effort),
        }
        models.append(base_entry)
        # Virtual "name:effort" models for clients that can't send
        # reasoning_effort; clients that can should use the base model.
        for effort in virtual_efforts(srv):
            vname = f"{model_name}:{effort}"
            models.append({**base_entry, "id": vname})
    return JSONResponse({"object": "list", "data": models})


# ---------------------------------------------------------------------------
# POST routes — passthrough
# ---------------------------------------------------------------------------


def _openai_error(exc: HTTPException) -> JSONResponse:
    """Gateway error in OpenAI's shape, so clients surface the message."""
    detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
    error: dict[str, Any] = {
        "message": detail.get("error", "error"),
        "type": "invalid_request_error" if exc.status_code < 500 else "api_error",
        "code": exc.status_code,
    }
    if "allowed_efforts" in detail:
        error["param"] = "reasoning_effort"
        error["allowed_efforts"] = detail["allowed_efforts"]
    return JSONResponse({"error": error}, status_code=exc.status_code)


async def _forward(request: Request, path: str, *, apply_effort: bool = False) -> Response:
    try:
        body, resp = await open_upstream(request, path, apply_effort=apply_effort)
        return await relay(body, resp)
    except HTTPException as exc:
        return _openai_error(exc)


async def open_upstream(
    request: Request,
    path: str,
    *,
    apply_effort: bool = False,
    prepare: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], httpx.Response]:
    """Send a JSON request to the model's upstream; returns (sent body, open response).

    Resolves the server from `model`, strips any virtual suffix, lets
    `prepare` adapt a dialect's body, then validates and applies the effort.
    The caller must close the response (`relay` does).
    """
    try:
        body: dict[str, Any] = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail={"error": "request body must be JSON"})
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail={"error": "request body must be a JSON object"})
    model = body.get("model", "")
    srv = get_subserver(model)
    body["model"], _ = split_virtual_model(model)
    if prepare:
        prepare(body)
    if apply_effort:
        _apply_reasoning_effort(body, srv, model, dict(body))

    client = get_client()
    upstream = client.build_request("POST", f"{srv.url}{path}", json=body, timeout=_TIMEOUT)
    try:
        resp = await client.send(upstream, stream=True)
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail={"error": "upstream unreachable"})
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail={"error": "upstream timeout"})
    return body, resp


async def relay(body: dict[str, Any], resp: httpx.Response) -> Response:
    """Relay an upstream response unchanged.

    Streaming responses are relayed byte for byte (SSE framing untouched);
    upstream errors keep their status code and body.
    """
    media_type = resp.headers.get("content-type", "application/json")
    if body.get("stream") and resp.status_code == 200:
        return StreamingResponse(
            resp.aiter_raw(), media_type=media_type, background=BackgroundTask(resp.aclose)
        )
    try:
        content = await resp.aread()
    finally:
        await resp.aclose()
    return Response(content=content, status_code=resp.status_code, media_type=media_type)


@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: Request) -> Response:
    return await _forward(request, "/v1/chat/completions", apply_effort=True)


@router.post("/v1/responses", response_model=None)
async def responses(request: Request) -> Response:
    return await _forward(request, "/v1/responses", apply_effort=True)


@router.post("/v1/completions", response_model=None)
async def completions(request: Request) -> Response:
    return await _forward(request, "/v1/completions")


@router.post("/v1/embeddings", response_model=None)
async def embeddings(request: Request) -> Response:
    return await _forward(request, "/v1/embeddings")
