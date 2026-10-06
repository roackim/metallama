from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, Body, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.routing import APIRoute
from starlette.background import BackgroundTask

from ..http_client import get_client, shared_client
from .probe import probe_one, _DEFAULT_CONTEXT_LENGTH
from .reasoning import apply_reasoning
from .registry import effective_reasoning_efforts, get_all_subservers, get_subserver, split_virtual_model, virtual_efforts
from .schemas import OllamaChatRequest, OllamaGenerateRequest, OllamaShowRequest

class _OllamaRoute(APIRoute):
    """Errors in Ollama's shape: `{"error": "message"}` with the real status.

    FastAPI renders HTTPException as `{"detail": ...}` and validation errors as
    422, neither of which Ollama clients read (they take the top-level `error`).
    """

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            try:
                return await handler(request)
            except HTTPException as exc:
                detail = exc.detail
                message = detail.get("error") if isinstance(detail, dict) else detail
                return JSONResponse({"error": str(message)}, status_code=exc.status_code)
            except RequestValidationError as exc:
                first = exc.errors()[0] if exc.errors() else {}
                where = ".".join(str(x) for x in first.get("loc", ())[1:])
                return JSONResponse({"error": f"invalid request: {where}: {first.get('msg', 'invalid')}".replace(": :", ":")},
                                    status_code=400)

        return wrapped


router = APIRouter(route_class=_OllamaRoute)

_TIMEOUT = httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0)
_HEALTH_TIMEOUT = httpx.Timeout(1.0)


def _digest(name: str) -> str:
    return "sha256:" + hashlib.sha256(name.encode()).hexdigest()


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _capabilities(srv: Any) -> list[str]:
    """Ollama capability list; "thinking" tells clients they may send `think`."""
    caps = ["completion"]
    if srv.tools:
        caps.append("tools")
    if srv.thinking:
        caps.append("thinking")
    if srv.vision:
        caps.append("vision")
    return caps


# ---------------------------------------------------------------------------
# GET / — Ollama clients ping the base URL to check the server is up
# ---------------------------------------------------------------------------


@router.get("")
@router.head("", include_in_schema=False)
async def root() -> PlainTextResponse:
    return PlainTextResponse("Ollama is running")


# ---------------------------------------------------------------------------
# GET /api/tags
# ---------------------------------------------------------------------------


@router.get("/api/tags")
async def list_tags() -> JSONResponse:
    models = []
    async with shared_client() as client:
        for srv in get_all_subservers():
            try:
                resp = await client.get(f"{srv.url}/health", timeout=_HEALTH_TIMEOUT)
                if resp.status_code != 200:
                    continue
            except (httpx.ConnectError, httpx.TimeoutException):
                continue
            # Server is up but probe may have missed it at startup — re-probe
            # lazily if we never successfully probed it (no upstream model id).
            if srv.context_length == _DEFAULT_CONTEXT_LENGTH or not srv.upstream_model_id:
                await probe_one(srv, client)
            model_name = srv.name
            families = [srv.family] if srv.family else []
            if srv.vision:
                families.append("clip")
            base_entry = {
                "name": model_name,
                "model": model_name,
                "modified_at": "2025-01-01T00:00:00Z",
                "size": srv.size,
                "digest": _digest(model_name),
                "details": {
                    "format": "gguf",
                    "family": srv.family,
                    "families": families,
                    "parameter_size": srv.parameter_size,
                    "quantization_level": srv.quantization,
                    "context_length": srv.context_length,
                },
                "capabilities": _capabilities(srv),
                "reasoning_efforts": effective_reasoning_efforts(srv),
            }
            models.append(base_entry)
            # Virtual "name:effort" models for clients that can't send an effort
            # parameter; clients that can should use the base model + `think`.
            for effort in virtual_efforts(srv):
                vname = f"{model_name}:{effort}"
                models.append({
                    **base_entry,
                    "name": vname,
                    "model": vname,
                    "digest": _digest(vname),
                })
    return JSONResponse({"models": models})


# ---------------------------------------------------------------------------
# GET /api/ps
# ---------------------------------------------------------------------------


@router.get("/api/ps")
async def list_running() -> JSONResponse:
    running = []
    async with shared_client() as client:
        for srv in get_all_subservers():
            try:
                resp = await client.get(f"{srv.url}/health", timeout=_HEALTH_TIMEOUT)
                if resp.status_code == 200:
                    model_name = srv.name
                    running.append(
                        {
                            "name": model_name,
                            "model": model_name,
                            "size": srv.size,
                            "digest": _digest(model_name),
                            "expires_at": None,
                            "size_vram": 0,
                            "details": {
                                "format": "gguf",
                                "family": srv.family,
                                "parameter_size": srv.parameter_size,
                                "quantization_level": srv.quantization,
                            },
                        }
                    )
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
    return JSONResponse({"models": running})


# ---------------------------------------------------------------------------
# GET /api/version
# ---------------------------------------------------------------------------


@router.get("/api/version")
async def version() -> JSONResponse:
    return JSONResponse({"version": "0.6.4"})


# ---------------------------------------------------------------------------
# POST /api/show
# ---------------------------------------------------------------------------


@router.post("/api/show")
async def show(req: OllamaShowRequest) -> JSONResponse:
    srv = get_subserver(req.model_name)
    # Re-probe lazily if we never successfully probed this server.
    if not srv.upstream_model_id:
        async with shared_client() as client:
            await probe_one(srv, client)
    arch = srv.family
    model_name = srv.name
    families = [arch] if arch else []
    if srv.vision:
        families.append("clip")
    # Clients look up `<general.architecture>.context_length`, so the keys stay
    # consistent with the architecture field even when it is empty.
    model_info: dict[str, Any] = {
        "general.architecture": arch,
        f"{arch}.context_length": srv.context_length,
    }
    n_params = srv.upstream_meta.get("n_params")
    if n_params:
        model_info["general.parameter_count"] = n_params
    n_embd = srv.upstream_meta.get("n_embd")
    if n_embd:
        model_info[f"{arch}.embedding_length"] = n_embd

    return JSONResponse(
        {
            "model": model_name,
            "details": {
                "parent_model": "",
                "format": "gguf",
                "family": arch,
                "families": families,
                "parameter_size": srv.parameter_size,
                "quantization_level": srv.quantization,
                "context_length": srv.context_length,
            },
            "context_length": srv.context_length,
            "model_info": model_info,
            "modelinfo": model_info,
            "parameters": f"num_ctx {srv.context_length}",
            "capabilities": _capabilities(srv),
            "reasoning_efforts": effective_reasoning_efforts(srv),
        }
    )


# ---------------------------------------------------------------------------
# POST /api/chat
# ---------------------------------------------------------------------------


# Ollama option name → llama-server parameter name (llama-server's OpenAI
# endpoint also accepts its native sampler fields such as top_k / min_p).
_OPTION_MAP = {
    "temperature": "temperature",
    "top_p": "top_p",
    "top_k": "top_k",
    "min_p": "min_p",
    "typical_p": "typical_p",
    "seed": "seed",
    "stop": "stop",
    "num_predict": "max_tokens",
    "presence_penalty": "presence_penalty",
    "frequency_penalty": "frequency_penalty",
    "repeat_penalty": "repeat_penalty",
    "repeat_last_n": "repeat_last_n",
    "mirostat": "mirostat",
    "mirostat_tau": "mirostat_tau",
    "mirostat_eta": "mirostat_eta",
    "num_keep": "n_keep",
}


def _translate_options(options: dict[str, Any] | None) -> dict[str, Any]:
    if not options:
        return {}
    return {_OPTION_MAP[k]: v for k, v in options.items() if k in _OPTION_MAP}


def _ollama_message_to_openai(m: Any) -> dict[str, Any]:
    """Convert an Ollama chat message to OpenAI shape (tool calls included).

    Ollama sends images as a list of base64 strings in `images`. llama-server's
    OpenAI endpoint expects multimodal content parts (`image_url` with a
    `data:image/...;base64,...` URL). We convert when images are present.
    """
    out: dict[str, Any] = {"role": m.role, "content": m.content or ""}
    # Ollama returns past thinking as `thinking`; the template reads reasoning_content.
    thinking = getattr(m, "thinking", None)
    if m.role == "assistant" and isinstance(thinking, str) and thinking:
        out["reasoning_content"] = thinking
    if m.role == "tool":
        # OpenAI wants tool_call_id; Ollama clients send tool_name (and
        # sometimes tool_call_id). The field must exist for chat templates.
        out["tool_call_id"] = m.tool_call_id or m.tool_name or "call_0"
        if m.tool_name:
            out["name"] = m.tool_name
    if m.tool_calls:
        calls = []
        for i, tc in enumerate(m.tool_calls):
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            args = fn.get("arguments", {})
            if not isinstance(args, str):
                args = json.dumps(args)
            calls.append({
                "id": tc.get("id") or f"call_{i}",
                "type": "function",
                "function": {"name": fn.get("name", ""), "arguments": args},
            })
        out["tool_calls"] = calls
    if m.images:
        out["content"] = _image_parts(m.content or "", m.images)
    return out


def _openai_tool_calls_to_ollama(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI tool_calls (arguments as JSON string) → Ollama shape (dict)."""
    out = []
    for tc in calls:
        fn = tc.get("function", {})
        args = fn.get("arguments", "")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = {"_raw": args}
        out.append({
            "id": tc.get("id"),
            "function": {"name": fn.get("name", ""), "arguments": args},
        })
    return out


def _done_reason(finish_reason: str | None) -> str:
    return {"tool_calls": "tool_calls", "length": "length"}.get(finish_reason or "", "stop")


async def _sse_events(resp: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Parse an OpenAI SSE stream line-safely (chunks can split mid-line)."""
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def _ollama_error(message: str, status_code: int) -> JSONResponse:
    """Ollama clients read errors from a top-level `error` string."""
    return JSONResponse({"error": message}, status_code=status_code)


def _upstream_error_message(raw: bytes) -> str:
    """Extract llama-server's error message from an error response body."""
    try:
        err = json.loads(raw).get("error")
    except (json.JSONDecodeError, AttributeError):
        err = None
    if isinstance(err, dict) and err.get("message"):
        return str(err["message"])
    if isinstance(err, str):
        return err
    return raw.decode(errors="replace")[:300] or "upstream error"


def _response_format(fmt: Any) -> dict[str, Any] | None:
    """Ollama `format` ("json" or a JSON schema) → OpenAI `response_format`."""
    if fmt == "json":
        # llama-server leaves a bare json_object unconstrained (the model may wrap
        # the JSON in markdown fences); a schema makes the grammar enforce it.
        return {"type": "json_schema", "json_schema": {"name": "response", "schema": {"type": "object"}}}
    if isinstance(fmt, dict):
        return {"type": "json_schema", "json_schema": {"name": "response", "schema": fmt}}
    return None


# Base64 prefixes of common image signatures (Ollama sends bare base64, no type).
_IMAGE_MAGIC = {"iVBORw0KGgo": "image/png", "/9j/": "image/jpeg", "R0lGOD": "image/gif", "UklGR": "image/webp"}


def _image_mime(b64: str) -> str:
    return next((mime for magic, mime in _IMAGE_MAGIC.items() if b64.startswith(magic)), "image/jpeg")


def _image_parts(text: str, images: list[str] | None) -> str | list[dict[str, Any]]:
    """Text plus base64 images → OpenAI multimodal content (plain text if no images)."""
    if not images:
        return text
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    for img in images:
        # If the client already sent a data: URL, pass it through.
        url = img if img.startswith("data:") else f"data:{_image_mime(img)};base64,{img}"
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts


def _done_stats(usage: dict[str, Any] | None, timings: dict[str, Any] | None) -> dict[str, Any]:
    """Token counts and durations (ns) for Ollama's final `done` object."""
    usage = usage or {}
    timings = timings or {}
    prompt_ns = int(float(timings.get("prompt_ms") or 0) * 1e6)
    eval_ns = int(float(timings.get("predicted_ms") or 0) * 1e6)
    return {
        "total_duration": prompt_ns + eval_ns,
        "load_duration": 0,
        "prompt_eval_count": usage.get("prompt_tokens") or timings.get("prompt_n") or 0,
        "prompt_eval_duration": prompt_ns,
        "eval_count": usage.get("completion_tokens") or timings.get("predicted_n") or 0,
        "eval_duration": eval_ns,
    }


def _frame(model: str, shape: str, *, content: str = "", thinking: str = "",
           tool_calls: list[dict[str, Any]] | None = None, done: bool = False, **extra: Any) -> dict[str, Any]:
    """One Ollama response object, shaped for /api/chat or /api/generate."""
    out: dict[str, Any] = {"model": model, "created_at": _now()}
    if shape == "chat":
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if thinking:
            message["thinking"] = thinking
        if tool_calls:
            message["tool_calls"] = tool_calls
        out["message"] = message
    else:
        out["response"] = content
        if thinking:
            out["thinking"] = thinking
    out["done"] = done
    out.update(extra)
    return out


def _load_response(model: str, shape: str, keep_alive: Any) -> JSONResponse:
    """Empty chat/generate = Ollama's load/unload ping; nothing to send upstream."""
    unload = keep_alive in (0, "0", "0s", "0m")
    return JSONResponse(_frame(model, shape, done=True, done_reason="unload" if unload else "load"))


async def _stream_chat(model: str, shape: str, resp: httpx.Response) -> AsyncIterator[str]:
    """Translate an OpenAI SSE chat stream → Ollama NDJSON stream.

    Content and thinking deltas stream through; tool-call fragments are
    accumulated and emitted as one complete message (Ollama semantics), then a
    final done line carries the finish reason, token counts and durations.
    """
    pending_calls: dict[int, dict[str, Any]] = {}
    finish: str | None = None
    usage: dict[str, Any] | None = None
    timings: dict[str, Any] | None = None

    async for data in _sse_events(resp):
        usage = data.get("usage") or usage
        timings = data.get("timings") or timings
        choice = data.get("choices", [{}])[0] if data.get("choices") else {}
        finish = choice.get("finish_reason") or finish
        delta = choice.get("delta", {})

        content = delta.get("content") or ""
        thinking = delta.get("reasoning_content") or ""
        if content or thinking:
            yield json.dumps(_frame(model, shape, content=content, thinking=thinking)) + "\n"

        for frag in delta.get("tool_calls") or []:
            idx = frag.get("index", 0)
            slot = pending_calls.setdefault(idx, {"id": None, "name": "", "arguments": ""})
            if frag.get("id"):
                slot["id"] = frag["id"]
            fn = frag.get("function", {})
            if fn.get("name"):
                slot["name"] += fn["name"]
            if fn.get("arguments"):
                slot["arguments"] += fn["arguments"]

    if pending_calls:
        calls = _openai_tool_calls_to_ollama([
            {"id": slot["id"], "function": {"name": slot["name"], "arguments": slot["arguments"]}}
            for _, slot in sorted(pending_calls.items())
        ])
        yield json.dumps(_frame(model, shape, tool_calls=calls)) + "\n"

    yield json.dumps(_frame(
        model, shape, done=True, done_reason=_done_reason(finish), **_done_stats(usage, timings),
    )) + "\n"


async def _run_chat(model: str, shape: str, srv_url: str, payload: dict[str, Any]) -> StreamingResponse | JSONResponse:
    """Send a chat payload upstream and answer in Ollama chat/generate shape."""
    if payload.get("stream"):
        payload["stream_options"] = {"include_usage": True, **(payload.get("stream_options") or {})}
        try:
            client = get_client()
            resp = await client.send(
                client.build_request("POST", f"{srv_url}/v1/chat/completions", json=payload, timeout=_TIMEOUT),
                stream=True,
            )
        except httpx.ConnectError:
            return _ollama_error("model server unreachable (loading or stopped)", 503)
        except httpx.TimeoutException:
            return _ollama_error("upstream timeout", 504)
        if resp.status_code != 200:
            raw = await resp.aread()
            await resp.aclose()
            return _ollama_error(_upstream_error_message(raw), resp.status_code)

        async def generate() -> AsyncIterator[bytes]:
            try:
                async for line in _stream_chat(model, shape, resp):
                    yield line.encode()
            except (httpx.ReadError, httpx.TimeoutException, httpx.RemoteProtocolError):
                # Headers are already sent; report in-band like Ollama does.
                yield (json.dumps({"error": "upstream disconnected"}) + "\n").encode()

        return StreamingResponse(generate(), media_type="application/x-ndjson", background=BackgroundTask(resp.aclose))

    try:
        async with shared_client() as client:
            resp = await client.post(f"{srv_url}/v1/chat/completions", json=payload, timeout=_TIMEOUT)
    except httpx.ConnectError:
        return _ollama_error("model server unreachable (loading or stopped)", 503)
    except httpx.TimeoutException:
        return _ollama_error("upstream timeout", 504)
    if resp.status_code != 200:
        return _ollama_error(_upstream_error_message(resp.content), resp.status_code)

    data = resp.json()
    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})
    calls = message.get("tool_calls")
    return JSONResponse(_frame(
        model, shape,
        content=message.get("content") or "",
        thinking=message.get("reasoning_content") or "",
        tool_calls=_openai_tool_calls_to_ollama(calls) if calls else None,
        done=True,
        done_reason=_done_reason(choice.get("finish_reason")),
        **_done_stats(data.get("usage"), data.get("timings")),
    ))


def _base_payload(model: str, stream: bool, options: dict[str, Any] | None, fmt: Any) -> dict[str, Any]:
    # Strip any virtual reasoning-effort suffix so llama-server receives the
    # real model id, not "name:xhigh".
    payload: dict[str, Any] = {
        "model": split_virtual_model(model)[0],
        "stream": stream,
        **_translate_options(options),
    }
    response_format = _response_format(fmt)
    if response_format:
        payload["response_format"] = response_format
    return payload


# metallama extensions (not part of Ollama's API), read from the request's extra
# top-level fields: the same reasoning replay controls as /openai, and
# stream_options.
_EXTENSION_FIELDS = (
    "preserve_reasoning", "preserve_thinking", "clear_thinking", "reasoning", "chat_template_kwargs",
    "stream_options",
)


def _apply_extensions(payload: dict[str, Any], body: dict[str, Any]) -> None:
    for key in _EXTENSION_FIELDS:
        if key in body:
            payload[key] = body[key]


@router.post("/api/chat", response_model=None)
async def chat(req: OllamaChatRequest) -> StreamingResponse | JSONResponse:
    srv = get_subserver(req.model)
    if not req.messages:
        return _load_response(req.model, "chat", req.keep_alive)
    payload = _base_payload(req.model, req.stream, req.options, req.format)
    payload["messages"] = [_ollama_message_to_openai(m) for m in req.messages]
    if req.tools:
        payload["tools"] = req.tools
    _apply_extensions(payload, body := req.model_dump(exclude_none=True))
    apply_reasoning(payload, srv, req.model, body)
    return await _run_chat(req.model, "chat", srv.url, payload)


# ---------------------------------------------------------------------------
# POST /api/generate
# ---------------------------------------------------------------------------


async def _stream_generate_raw(model: str, resp: httpx.Response) -> AsyncIterator[str]:
    """Translate an OpenAI SSE completions stream → Ollama generate NDJSON."""
    finish: str | None = None
    usage: dict[str, Any] | None = None
    timings: dict[str, Any] | None = None
    async for data in _sse_events(resp):
        usage = data.get("usage") or usage
        timings = data.get("timings") or timings
        choice = data.get("choices", [{}])[0] if data.get("choices") else {}
        finish = choice.get("finish_reason") or finish
        text = choice.get("text", "")
        if text:
            yield json.dumps(_frame(model, "generate", content=text)) + "\n"
    yield json.dumps(_frame(
        model, "generate", done=True, done_reason=_done_reason(finish), **_done_stats(usage, timings),
    )) + "\n"


async def _run_raw_generate(model: str, srv_url: str, payload: dict[str, Any]) -> StreamingResponse | JSONResponse:
    """`raw: true` generate: the prompt goes to llama-server untemplated."""
    if payload.get("stream"):
        payload["stream_options"] = {"include_usage": True, **(payload.get("stream_options") or {})}
        try:
            client = get_client()
            resp = await client.send(
                client.build_request("POST", f"{srv_url}/v1/completions", json=payload, timeout=_TIMEOUT),
                stream=True,
            )
        except httpx.ConnectError:
            return _ollama_error("model server unreachable (loading or stopped)", 503)
        except httpx.TimeoutException:
            return _ollama_error("upstream timeout", 504)
        if resp.status_code != 200:
            raw = await resp.aread()
            await resp.aclose()
            return _ollama_error(_upstream_error_message(raw), resp.status_code)

        async def generate() -> AsyncIterator[bytes]:
            try:
                async for line in _stream_generate_raw(model, resp):
                    yield line.encode()
            except (httpx.ReadError, httpx.TimeoutException, httpx.RemoteProtocolError):
                yield (json.dumps({"error": "upstream disconnected"}) + "\n").encode()

        return StreamingResponse(generate(), media_type="application/x-ndjson", background=BackgroundTask(resp.aclose))

    try:
        async with shared_client() as client:
            resp = await client.post(f"{srv_url}/v1/completions", json=payload, timeout=_TIMEOUT)
    except httpx.ConnectError:
        return _ollama_error("model server unreachable (loading or stopped)", 503)
    except httpx.TimeoutException:
        return _ollama_error("upstream timeout", 504)
    if resp.status_code != 200:
        return _ollama_error(_upstream_error_message(resp.content), resp.status_code)

    data = resp.json()
    choice = data.get("choices", [{}])[0]
    return JSONResponse(_frame(
        model, "generate",
        content=choice.get("text", ""),
        done=True,
        done_reason=_done_reason(choice.get("finish_reason")),
        **_done_stats(data.get("usage"), data.get("timings")),
    ))


@router.post("/api/generate", response_model=None)
async def generate_endpoint(req: OllamaGenerateRequest) -> StreamingResponse | JSONResponse:
    srv = get_subserver(req.model)
    if not req.prompt and not req.images:
        return _load_response(req.model, "generate", req.keep_alive)
    payload = _base_payload(req.model, req.stream, req.options, req.format)

    if req.raw:
        payload["prompt"] = req.prompt
        return await _run_raw_generate(req.model, srv.url, payload)

    # Like Ollama, a non-raw prompt is rendered through the model's chat template.
    messages: list[dict[str, Any]] = []
    if req.system:
        messages.append({"role": "system", "content": req.system})
    messages.append({"role": "user", "content": _image_parts(req.prompt, req.images)})
    payload["messages"] = messages
    _apply_extensions(payload, body := req.model_dump(exclude_none=True))
    apply_reasoning(payload, srv, req.model, body)
    return await _run_chat(req.model, "generate", srv.url, payload)


# ---------------------------------------------------------------------------
# POST /api/embed, /api/embeddings
# ---------------------------------------------------------------------------


async def _embed(model: str, inputs: list[str]) -> tuple[list[list[float]], int] | JSONResponse:
    srv = get_subserver(model)
    payload = {"model": split_virtual_model(model)[0], "input": inputs}
    try:
        async with shared_client() as client:
            resp = await client.post(f"{srv.url}/v1/embeddings", json=payload, timeout=_TIMEOUT)
    except httpx.ConnectError:
        return _ollama_error("model server unreachable (loading or stopped)", 503)
    except httpx.TimeoutException:
        return _ollama_error("upstream timeout", 504)
    if resp.status_code != 200:
        return _ollama_error(_upstream_error_message(resp.content), resp.status_code)
    data = resp.json()
    rows = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
    return [row.get("embedding", []) for row in rows], (data.get("usage") or {}).get("prompt_tokens", 0)


@router.post("/api/embed", response_model=None)
async def embed(body: dict[str, Any] = Body(...)) -> JSONResponse:
    model = body.get("model", "")
    raw = body.get("input", [])
    result = await _embed(model, [raw] if isinstance(raw, str) else list(raw))
    if isinstance(result, JSONResponse):
        return result
    embeddings, prompt_tokens = result
    return JSONResponse({"model": model, "embeddings": embeddings, "prompt_eval_count": prompt_tokens})


@router.post("/api/embeddings", response_model=None)
async def embeddings_legacy(body: dict[str, Any] = Body(...)) -> JSONResponse:
    result = await _embed(body.get("model", ""), [body.get("prompt", "")])
    if isinstance(result, JSONResponse):
        return result
    embeddings, _ = result
    return JSONResponse({"embedding": embeddings[0] if embeddings else []})


# ---------------------------------------------------------------------------
# Stubbed management endpoints
# ---------------------------------------------------------------------------

_NOT_SUPPORTED = JSONResponse({"error": "not supported"}, status_code=400)


@router.post("/api/pull")
async def pull() -> JSONResponse:
    return _NOT_SUPPORTED


@router.post("/api/push")
async def push() -> JSONResponse:
    return _NOT_SUPPORTED


@router.post("/api/copy")
async def copy() -> JSONResponse:
    return _NOT_SUPPORTED


@router.post("/api/delete")
async def delete() -> JSONResponse:
    return _NOT_SUPPORTED


@router.post("/api/create")
async def create() -> JSONResponse:
    return _NOT_SUPPORTED
