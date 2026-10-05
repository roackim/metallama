"""OpenAI-compatible gateway, mounted at /openai (and at /ollama for legacy clients).

A thin router over llama-server's own OpenAI API: it picks the upstream from
the model name, strips any virtual "name:effort" suffix, validates the
reasoning effort, and forwards the body and the response unchanged.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Callable, NamedTuple

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from ...http_client import get_client, shared_client
from ..probe import probe_one, _DEFAULT_CONTEXT_LENGTH
from ..replay import apply_replay, apply_replay_responses
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

# A streaming request still waiting for upstream headers after this long (long
# prompt processing, model swap) gets its 200 early and SSE comment keep-alives,
# so clients with a read timeout don't give up and replay the request. Faster
# failures keep their real status code.
_KEEPALIVE_GRACE = 10.0
_KEEPALIVE_INTERVAL = 10.0


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
        prepared = await prepare_upstream(
            request, path, apply_effort=apply_effort, usage=path.endswith("/chat/completions")
        )
        return await respond(prepared)
    except HTTPException as exc:
        return _openai_error(exc)


StreamWrap = Callable[[httpx.Response], AsyncIterator[bytes]]


async def respond(prepared: Prepared, wrap: StreamWrap | None = None) -> Response:
    """Send the request; relay the answer, with keep-alives for slow streams.

    `wrap` replaces the relay of a successful stream (a dialect's translation);
    it runs after the keep-alive phase. Either way, `model` is rewritten to
    what the client asked for (llama-server reports its GGUF path).
    """
    body, client, upstream, model = prepared.body, prepared.client, prepared.upstream, prepared.model
    if not body.get("stream"):
        return await relay(body, await _send(client, upstream), model)
    send = asyncio.ensure_future(_send(client, upstream))
    try:
        done, _ = await asyncio.wait({send}, timeout=_KEEPALIVE_GRACE)
    except asyncio.CancelledError:
        send.cancel()
        raise
    if done:
        resp = send.result()
        if resp.status_code != 200:
            return await relay(body, resp, model)
        return StreamingResponse(_relay_stream(resp, wrap, model), media_type="text/event-stream",
                                 background=BackgroundTask(resp.aclose))
    return StreamingResponse(_keepalive_stream(send, wrap, model), media_type="text/event-stream")


async def _keepalive_stream(
    send: "asyncio.Future[httpx.Response]", wrap: StreamWrap | None, model: str
) -> AsyncIterator[bytes]:
    """SSE comments while upstream is silent, then its stream relayed."""
    try:
        while not send.done():
            await asyncio.wait({send}, timeout=_KEEPALIVE_INTERVAL)
            if not send.done():
                yield b": keepalive\n\n"
        try:
            resp = send.result()
        except HTTPException as exc:
            yield _sse_error(exc)
            return
    finally:
        if not send.done():
            send.cancel()
    try:
        if resp.status_code != 200:
            yield _sse_error(HTTPException(resp.status_code, {"error": _upstream_message(await resp.aread())}))
            return
        async for chunk in _relay_stream(resp, wrap, model):
            yield chunk
    finally:
        await resp.aclose()


async def _relay_stream(resp: httpx.Response, wrap: StreamWrap | None, model: str) -> AsyncIterator[bytes]:
    """The upstream stream (or its dialect translation) with `model` rewritten per SSE line."""
    source = wrap(resp) if wrap else resp.aiter_raw()
    buffer = b""
    async for chunk in source:
        buffer += chunk
        *lines, buffer = buffer.split(b"\n")
        for line in lines:
            yield _with_model_line(line, model) + b"\n"
    if buffer:
        yield _with_model_line(buffer, model)


def _with_model_line(line: bytes, model: str) -> bytes:
    """Rewrite `model` in one SSE `data:` line; anything else passes untouched."""
    if not line.startswith(b"data:"):
        return line
    payload = line[5:].strip()
    if not payload or payload == b"[DONE]":
        return line
    try:
        obj = json.loads(payload)
    except ValueError:
        return line
    if not _set_model(obj, model):
        return line
    return b"data: " + json.dumps(obj).encode()


def _set_model(obj: Any, model: str) -> bool:
    """Point the response's `model` at the client's name (also inside Responses `response`)."""
    if not isinstance(obj, dict):
        return False
    changed = False
    if "model" in obj:
        obj["model"] = model
        changed = True
    inner = obj.get("response")
    if isinstance(inner, dict) and "model" in inner:
        inner["model"] = model
        changed = True
    return changed


def _upstream_message(raw: bytes) -> str:
    """The human message of an upstream error body (OpenAI shape), else its text."""
    text = raw.decode("utf-8", "replace")
    try:
        err = json.loads(text).get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
        if isinstance(err, str):
            return err
    except (ValueError, AttributeError):
        pass
    return text[:500] or "upstream error"


def _sse_error(exc: HTTPException) -> bytes:
    """An error after the 200 was committed.

    OpenRouter's documented shape: a chunk with a top-level `error` and
    `finish_reason: "error"` so streaming parsers terminate cleanly, then [DONE].
    """
    error = json.loads(_openai_error(exc).body)["error"]
    chunk = {
        "object": "chat.completion.chunk",
        "error": error,
        "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "error"}],
    }
    return f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()


class Prepared(NamedTuple):
    """An upstream request ready to send, plus what the client called the model."""

    body: dict[str, Any]
    upstream: httpx.Request
    client: httpx.AsyncClient
    model: str


async def prepare_upstream(
    request: Request,
    path: str,
    *,
    apply_effort: bool = False,
    prepare: Callable[[dict[str, Any]], None] | None = None,
    usage: bool = False,
) -> "Prepared":
    """Build the upstream request for a JSON call (nothing is sent yet).

    Resolves the server from `model`, strips any virtual suffix, lets
    `prepare` adapt a dialect's body, then validates and applies the effort.
    With `usage`, a streamed chat gets `stream_options.include_usage` unless
    the client set it, so the stream always ends with a usage chunk.
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
    # Replay first: it reads `reasoning.context`, which the effort step consumes.
    if path.endswith("/chat/completions"):
        apply_replay(body)
    elif path.endswith("/responses"):
        if body.get("previous_response_id"):
            raise HTTPException(status_code=400, detail={
                "error": "previous_response_id is not supported: this gateway is stateless, "
                         "send the full conversation in `input`"})
        apply_replay_responses(body)
    if apply_effort:
        _apply_reasoning_effort(body, srv, model, dict(body))
    if usage and body.get("stream"):
        opts = body.get("stream_options")
        if not isinstance(opts, dict):
            opts = body["stream_options"] = {}
        opts.setdefault("include_usage", True)

    client = get_client()
    return Prepared(
        body, client.build_request("POST", f"{srv.url}{path}", json=body, timeout=_TIMEOUT), client, model
    )


async def _send(client: httpx.AsyncClient, upstream: httpx.Request) -> httpx.Response:
    try:
        return await client.send(upstream, stream=True)
    except httpx.ConnectError:
        # Clients retry 503 with backoff (a model that is loading or restarting).
        raise HTTPException(status_code=503, detail={"error": "model server unreachable (loading or stopped)"})
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail={"error": "upstream timeout"})


async def relay(body: dict[str, Any], resp: httpx.Response, model: str | None = None) -> Response:
    """Relay an upstream response; upstream errors keep their status and body.

    With `model`, a JSON answer gets its `model` rewritten to the client's name.
    """
    media_type = resp.headers.get("content-type", "application/json")
    try:
        content = await resp.aread()
    finally:
        await resp.aclose()
    if model and resp.status_code == 200 and "json" in media_type:
        try:
            obj = json.loads(content)
        except ValueError:
            obj = None
        if _set_model(obj, model):
            content = json.dumps(obj).encode()
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
