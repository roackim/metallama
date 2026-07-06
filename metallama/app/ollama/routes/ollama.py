from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from ..probe import probe_one, _DEFAULT_CONTEXT_LENGTH
from ..registry import get_subserver, get_all_subservers
from ..schemas import OllamaChatRequest, OllamaGenerateRequest, OllamaShowRequest

router = APIRouter()

_TIMEOUT = httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0)
_HEALTH_TIMEOUT = httpx.Timeout(1.0)


def _digest(name: str) -> str:
    return "sha256:" + hashlib.sha256(name.encode()).hexdigest()


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# GET /api/tags
# ---------------------------------------------------------------------------


@router.get("/api/tags")
async def list_tags() -> JSONResponse:
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
            arch = srv.upstream_meta.get("general.architecture", srv.family)
            quant = srv.upstream_meta.get("quantization", "unknown")
            model_name = srv.upstream_model_id or srv.name
            models.append(
                {
                    "name": model_name,
                    "model": model_name,
                    "modified_at": "2025-01-01T00:00:00Z",
                    "size": srv.size,
                    "digest": _digest(model_name),
                    "details": {
                        "format": "gguf",
                        "family": arch,
                        "families": [arch],
                        "parameter_size": srv.parameter_size,
                        "quantization_level": quant,
                        "context_length": srv.context_length,
                    },
                }
            )
    return JSONResponse({"models": models})


# ---------------------------------------------------------------------------
# GET /api/ps
# ---------------------------------------------------------------------------


@router.get("/api/ps")
async def list_running() -> JSONResponse:
    running = []
    async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
        for srv in get_all_subservers():
            try:
                resp = await client.get(f"{srv.url}/health")
                if resp.status_code == 200:
                    model_name = srv.upstream_model_id or srv.name
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
    arch = srv.upstream_meta.get("general.architecture", srv.family)
    n_embd = srv.upstream_meta.get("n_embd", 4096)
    quant = srv.upstream_meta.get("quantization", "unknown")
    model_name = srv.upstream_model_id or srv.name
    model_info = {
        "general.architecture": arch,
        "general.parameter_count": srv.parameter_size,
        f"{arch}.context_length": srv.context_length,
        f"{arch}.embedding_length": n_embd,
    }

    return JSONResponse(
        {
            "model": model_name,
            "details": {
                "parent_model": "",
                "format": "gguf",
                "family": arch,
                "families": [arch],
                "parameter_size": srv.parameter_size,
                "quantization_level": quant,
                "context_length": srv.context_length,
            },
            "context_length": srv.context_length,
            "model_info": model_info,
            "modelinfo": model_info,
            "parameters": f"num_ctx {srv.context_length}\nstop \"<|im_end|>\"",
            "capabilities": ["completion", "tools"],
        }
    )


# ---------------------------------------------------------------------------
# POST /api/chat
# ---------------------------------------------------------------------------


# Ollama option name → OpenAI parameter name
_OPTION_MAP = {
    "temperature": "temperature",
    "top_p": "top_p",
    "seed": "seed",
    "stop": "stop",
    "num_predict": "max_tokens",
    "presence_penalty": "presence_penalty",
    "frequency_penalty": "frequency_penalty",
}


def _translate_options(options: dict[str, Any] | None) -> dict[str, Any]:
    if not options:
        return {}
    return {_OPTION_MAP[k]: v for k, v in options.items() if k in _OPTION_MAP}


def _ollama_message_to_openai(m: Any) -> dict[str, Any]:
    """Convert an Ollama chat message to OpenAI shape (tool calls included)."""
    out: dict[str, Any] = {"role": m.role, "content": m.content or ""}
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
        out["images"] = m.images
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


async def _stream_chat(model: str, resp: httpx.Response) -> AsyncIterator[str]:
    """Translate OpenAI SSE stream → Ollama NDJSON stream.

    Content deltas stream through; tool-call fragments are accumulated and
    emitted as one complete message (Ollama semantics), then a final done
    line carries the finish reason.
    """
    pending_calls: dict[int, dict[str, Any]] = {}
    finish: str | None = None

    async for data in _sse_events(resp):
        choice = data.get("choices", [{}])[0] if data.get("choices") else {}
        finish = choice.get("finish_reason") or finish
        delta = choice.get("delta", {})

        content = delta.get("content", "")
        if content:
            yield json.dumps({
                "model": model,
                "created_at": _now(),
                "message": {"role": "assistant", "content": content},
                "done": False,
            }) + "\n"

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
        yield json.dumps({
            "model": model,
            "created_at": _now(),
            "message": {"role": "assistant", "content": "", "tool_calls": calls},
            "done": False,
        }) + "\n"

    yield json.dumps({
        "model": model,
        "created_at": _now(),
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": _done_reason(finish),
    }) + "\n"


@router.post("/api/chat", response_model=None)
async def chat(req: OllamaChatRequest) -> StreamingResponse | JSONResponse:
    srv = get_subserver(req.model)
    payload: dict[str, Any] = {
        "model": req.model,
        "messages": [_ollama_message_to_openai(m) for m in req.messages],
        "stream": req.stream,
        **_translate_options(req.options),
    }
    if req.tools:
        payload["tools"] = req.tools
    if req.format == "json":
        payload["response_format"] = {"type": "json_object"}

    if req.stream:
        async def generate() -> AsyncIterator[bytes]:
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    async with client.stream("POST", f"{srv.url}/v1/chat/completions", json=payload) as resp:
                        if resp.status_code != 200:
                            body = await resp.aread()
                            yield (json.dumps({"error": f"upstream error: {body.decode(errors='replace')[:300]}"}) + "\n").encode()
                            return
                        async for chunk in _stream_chat(req.model, resp):
                            yield chunk.encode()
            except httpx.ConnectError:
                yield (json.dumps({"error": "upstream unreachable"}) + "\n").encode()
            except httpx.TimeoutException:
                yield (json.dumps({"error": "upstream timeout"}) + "\n").encode()

        return StreamingResponse(generate(), media_type="application/x-ndjson")

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{srv.url}/v1/chat/completions", json=payload)
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail={"error": "upstream unreachable"})
    except httpx.TimeoutException:
        raise HTTPException(status_code=502, detail={"error": "upstream timeout"})

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail={"error": f"upstream error: {resp.text[:300]}"})

    data = resp.json()
    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})
    out_message: dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("tool_calls"):
        out_message["tool_calls"] = _openai_tool_calls_to_ollama(message["tool_calls"])
    usage = data.get("usage", {})
    return JSONResponse({
        "model": req.model,
        "created_at": _now(),
        "message": out_message,
        "done": True,
        "done_reason": _done_reason(choice.get("finish_reason")),
        "prompt_eval_count": usage.get("prompt_tokens", 0),
        "eval_count": usage.get("completion_tokens", 0),
    })


# ---------------------------------------------------------------------------
# POST /api/generate
# ---------------------------------------------------------------------------


async def _stream_generate(model: str, resp: httpx.Response) -> AsyncIterator[str]:
    """Translate OpenAI SSE stream → Ollama generate NDJSON stream."""
    async for data in _sse_events(resp):
        text = data.get("choices", [{}])[0].get("text", "")
        if text:
            yield json.dumps({
                "model": model,
                "created_at": _now(),
                "response": text,
                "done": False,
            }) + "\n"
    yield json.dumps({"model": model, "created_at": _now(), "response": "", "done": True}) + "\n"


@router.post("/api/generate", response_model=None)
async def generate_endpoint(req: OllamaGenerateRequest) -> StreamingResponse | JSONResponse:
    srv = get_subserver(req.model)
    payload = {
        "model": req.model,
        "prompt": req.prompt,
        "stream": req.stream,
        **_translate_options(req.options),
    }

    if req.stream:
        async def generate() -> AsyncIterator[bytes]:
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    async with client.stream("POST", f"{srv.url}/v1/completions", json=payload) as resp:
                        if resp.status_code != 200:
                            yield (json.dumps({"error": "upstream error"}) + "\n").encode()
                            return
                        async for chunk in _stream_generate(req.model, resp):
                            yield chunk.encode()
            except httpx.ConnectError:
                yield (json.dumps({"error": "upstream unreachable"}) + "\n").encode()
            except httpx.TimeoutException:
                yield (json.dumps({"error": "upstream timeout"}) + "\n").encode()

        return StreamingResponse(generate(), media_type="application/x-ndjson")

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{srv.url}/v1/completions", json=payload)
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail={"error": "upstream unreachable"})
    except httpx.TimeoutException:
        raise HTTPException(status_code=502, detail={"error": "upstream timeout"})

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail={"error": "upstream error"})

    data = resp.json()
    text = data.get("choices", [{}])[0].get("text", "")
    return JSONResponse({
        "model": req.model,
        "created_at": _now(),
        "response": text,
        "done": True,
    })


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
