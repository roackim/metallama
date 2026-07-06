from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..probe import probe_one, _DEFAULT_CONTEXT_LENGTH
from ..registry import get_subserver, get_all_subservers

router = APIRouter()

_TIMEOUT = httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0)
_HEALTH_TIMEOUT = httpx.Timeout(1.0)


# ---------------------------------------------------------------------------
# GET /v1/models
# ---------------------------------------------------------------------------


@router.get("/v1/models")
async def list_models() -> JSONResponse:
    models = []
    async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
        for srv in get_all_subservers():
            try:
                resp = await client.get(f"{srv.url}/health")
                if resp.status_code != 200:
                    continue
            except (httpx.ConnectError, httpx.TimeoutException):
                continue
            # Server is up but probe may have missed it at startup — re-probe lazily
            if srv.context_length == _DEFAULT_CONTEXT_LENGTH:
                await probe_one(srv, client)
            model_name = srv.upstream_model_id or srv.name
            models.append(
                {
                    "id": model_name,
                    "object": "model",
                    "created": 1704067200,
                    "owned_by": "metallama",
                    "meta": {
                        **srv.upstream_meta,
                        "n_ctx": srv.context_length,
                    },
                    "context_length": srv.context_length,
                }
            )
    return JSONResponse({"object": "list", "data": models})


# ---------------------------------------------------------------------------
# POST /v1/chat/completions — passthrough
# ---------------------------------------------------------------------------


@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: Request) -> StreamingResponse | JSONResponse:
    body: dict[str, Any] = await request.json()
    model = body.get("model", "")
    srv = get_subserver(model)
    stream = body.get("stream", False)

    if stream:
        async def generate() -> AsyncIterator[bytes]:
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    async with client.stream("POST", f"{srv.url}/v1/chat/completions", json=body) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk
            except httpx.ConnectError:
                yield b"data: " + json.dumps({"error": "upstream unreachable"}).encode() + b"\n\n"
            except httpx.TimeoutException:
                yield b"data: " + json.dumps({"error": "upstream timeout"}).encode() + b"\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{srv.url}/v1/chat/completions", json=body)
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail={"error": "upstream unreachable"})
    except httpx.TimeoutException:
        raise HTTPException(status_code=502, detail={"error": "upstream timeout"})

    return JSONResponse(content=resp.json(), status_code=resp.status_code)


# ---------------------------------------------------------------------------
# POST /v1/completions — passthrough
# ---------------------------------------------------------------------------


@router.post("/v1/completions", response_model=None)
async def completions(request: Request) -> StreamingResponse | JSONResponse:
    body: dict[str, Any] = await request.json()
    model = body.get("model", "")
    srv = get_subserver(model)
    stream = body.get("stream", False)

    if stream:
        async def generate() -> AsyncIterator[bytes]:
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    async with client.stream("POST", f"{srv.url}/v1/completions", json=body) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk
            except httpx.ConnectError:
                yield b"data: " + json.dumps({"error": "upstream unreachable"}).encode() + b"\n\n"
            except httpx.TimeoutException:
                yield b"data: " + json.dumps({"error": "upstream timeout"}).encode() + b"\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{srv.url}/v1/completions", json=body)
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail={"error": "upstream unreachable"})
    except httpx.TimeoutException:
        raise HTTPException(status_code=502, detail={"error": "upstream timeout"})

    return JSONResponse(content=resp.json(), status_code=resp.status_code)


# ---------------------------------------------------------------------------
# POST /v1/embeddings — passthrough
# ---------------------------------------------------------------------------


@router.post("/v1/embeddings")
async def embeddings(request: Request) -> JSONResponse:
    body: dict[str, Any] = await request.json()
    model = body.get("model", "")
    srv = get_subserver(model)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{srv.url}/v1/embeddings", json=body)
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail={"error": "upstream unreachable"})
    except httpx.TimeoutException:
        raise HTTPException(status_code=502, detail={"error": "upstream timeout"})

    return JSONResponse(content=resp.json(), status_code=resp.status_code)
