"""OpenRouter-flavoured gateway, mounted at /openrouter (base_url .../openrouter/v1).

Serves the local models in OpenRouter's dialect so clients with an
"OpenRouter" provider type work unchanged. Built on the /openai passthrough,
with OpenRouter's conventions layered on top:

- /models entries in OpenRouter's shape (architecture, pricing, top_provider,
  supported_parameters, reasoning).
- Request `reasoning: {effort, enabled, exclude, max_tokens}` and the legacy
  `include_reasoning` flag; OpenRouter-only routing fields are dropped.
- Responses carry reasoning as `reasoning` (llama.cpp calls it
  `reasoning_content`), or omit it when excluded.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from ..registry import effective_reasoning_efforts, virtual_efforts
from .openai import _openai_error, _reasoning_fields, healthy_subservers, open_upstream

router = APIRouter()

# Request fields that only steer OpenRouter's own routing/billing; llama-server
# has no use for them.
_OPENROUTER_ONLY_FIELDS = ("provider", "models", "route", "transforms", "plugins", "usage", "user")

# Sampling/format parameters llama-server's chat endpoint honours.
_SUPPORTED_PARAMETERS = [
    "frequency_penalty", "logit_bias", "logprobs", "max_tokens", "min_p",
    "presence_penalty", "response_format", "seed", "stop", "structured_outputs",
    "temperature", "tool_choice", "tools", "top_k", "top_logprobs", "top_p",
]


# ---------------------------------------------------------------------------
# GET /v1/models
# ---------------------------------------------------------------------------


def _model_entry(model_id: str, srv: Any) -> dict[str, Any]:
    """One /models entry in OpenRouter's shape. No nulls (clients store TOML)."""
    allowed_efforts = effective_reasoning_efforts(srv)
    reasoning = _reasoning_fields(allowed_efforts, srv.default_reasoning_effort)
    input_modalities = ["text", "image"] if srv.vision else ["text"]
    return {
        "id": model_id,
        "canonical_slug": model_id,
        "name": model_id,
        "created": 1704067200,
        "description": "Local llama.cpp model served by metallama.",
        "context_length": srv.context_length,
        "architecture": {
            "modality": f"{'+'.join(input_modalities)}->text",
            "input_modalities": input_modalities,
            "output_modalities": ["text"],
            # llama-server doesn't report the architecture; OpenRouter's catch-all.
            "tokenizer": "Other",
        },
        "pricing": {"prompt": "0", "completion": "0", "request": "0", "image": "0"},
        "top_provider": {"context_length": srv.context_length, "is_moderated": False},
        "supported_parameters": sorted(
            _SUPPORTED_PARAMETERS + reasoning.get("supported_parameters", [])
        ),
        **({"reasoning": reasoning["reasoning"]} if reasoning else {}),
    }


@router.get("/v1/models")
async def list_models() -> JSONResponse:
    models = []
    for srv in await healthy_subservers():
        models.append(_model_entry(srv.name, srv))
        for effort in virtual_efforts(srv):
            models.append(_model_entry(f"{srv.name}:{effort}", srv))
    return JSONResponse({"data": models})


# ---------------------------------------------------------------------------
# POST /v1/chat/completions
# ---------------------------------------------------------------------------


def _wants_reasoning(body: dict[str, Any]) -> bool:
    """Whether the client wants reasoning text back (OpenRouter's default: yes)."""
    reasoning = body.get("reasoning") if isinstance(body.get("reasoning"), dict) else {}
    if reasoning.get("exclude") is True:
        return False
    return body.get("include_reasoning") is not False


def _prepare(body: dict[str, Any]) -> None:
    """Map OpenRouter request fields onto llama-server's chat body."""
    for field in _OPENROUTER_ONLY_FIELDS:
        body.pop(field, None)
    body.pop("include_reasoning", None)
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict):
        # `enabled: false` turns thinking off; `max_tokens` is ignored on
        # purpose (budgets hard-cut the reasoning). `effort` is read by the
        # shared effort resolver.
        if reasoning.get("enabled") is False and "effort" not in reasoning:
            body["reasoning_effort"] = "none"


def _rename_reasoning(part: dict[str, Any], keep: bool) -> None:
    """llama.cpp `reasoning_content` → OpenRouter `reasoning` (or drop it)."""
    text = part.pop("reasoning_content", None)
    if keep and text is not None:
        part["reasoning"] = text


async def _translate_stream(resp: httpx.Response, keep: bool) -> AsyncIterator[bytes]:
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload != "[DONE]":
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                chunk = None
            if isinstance(chunk, dict):
                for choice in chunk.get("choices") or []:
                    if isinstance(choice.get("delta"), dict):
                        _rename_reasoning(choice["delta"], keep)
                payload = json.dumps(chunk)
        yield f"data: {payload}\n\n".encode()


@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: Request) -> Response:
    try:
        keep: list[bool] = []
        def prepare(body: dict[str, Any]) -> None:
            keep.append(_wants_reasoning(body))
            _prepare(body)
        body, resp = await open_upstream(
            request, "/v1/chat/completions", apply_effort=True, prepare=prepare
        )
    except HTTPException as exc:
        return _openai_error(exc)
    keep_reasoning = keep[0]

    if body.get("stream") and resp.status_code == 200:
        return StreamingResponse(
            _translate_stream(resp, keep_reasoning),
            media_type="text/event-stream",
            background=BackgroundTask(resp.aclose),
        )
    try:
        content = await resp.aread()
    finally:
        await resp.aclose()
    media_type = resp.headers.get("content-type", "application/json")
    if resp.status_code != 200:
        return Response(content=content, status_code=resp.status_code, media_type=media_type)
    data = json.loads(content)
    for choice in data.get("choices") or []:
        if isinstance(choice.get("message"), dict):
            _rename_reasoning(choice["message"], keep_reasoning)
    return JSONResponse(data)
