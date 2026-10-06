from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

import httpx

from ..gguf import read_chat_template
from .registry import REASONING_EFFORTS, get_all_subservers
from .schemas import SubserverConfig

_PROBE_TIMEOUT = httpx.Timeout(3.0)

# Chat-template fragments that indicate the model emits separate thinking.
_THINKING_MARKERS = ("<think>", "enable_thinking", "reasoning_content")


def _infer_reasoning_efforts(chat_template: str) -> list[str]:
    """Infer the reasoning-effort values a chat template supports.

    Scans the Jinja template for string literals compared against
    `reasoning_effort` / `resolved_reasoning_effort` (e.g.
    `reasoning_effort == 'high'`, `not in ('xhigh', 'medium', 'low')`).
    "none" is supported when the template honours `enable_thinking`, which
    llama-server sets to false for reasoning_effort "none". Returns recognized
    values in canonical order. Empty if the template doesn't reference
    reasoning effort at all.
    """
    if not chat_template:
        return []
    found: set[str] = set()
    # Single-value comparisons: reasoning_effort == 'high'
    for m in re.finditer(
        r"(?:resolved_)?reasoning_effort\s*(?:==|!=|in|not\s+in)\s*\(?['\"]([a-zA-Z0-9_]+)['\"]",
        chat_template,
    ):
        found.add(m.group(1))
    # Tuple/list forms: not in ('xhigh', 'medium', 'low')
    for m in re.finditer(
        r"(?:resolved_)?reasoning_effort\s*(?:in|not\s+in)\s*\(([^)]*)\)",
        chat_template,
    ):
        for lit in re.findall(r"['\"]([a-zA-Z0-9_]+)['\"]", m.group(1)):
            found.add(lit)
    if found and "enable_thinking" in chat_template:
        found.add("none")
    # Keep only recognized values, in canonical order.
    return [v for v in REASONING_EFFORTS if v in found]


def _infer_default_effort(chat_template: str) -> str | None:
    """The effort a template applies when the request sends none.

    Matches `reasoning_effort|default('xhigh')`. None if the template doesn't
    declare one.
    """
    m = re.search(
        r"reasoning_effort\s*\|\s*default\(\s*['\"]([a-zA-Z0-9_]+)['\"]",
        chat_template or "",
    )
    return m.group(1) if m and m.group(1) in REASONING_EFFORTS else None


def server_chat_template(model_path: str | None, extra_args: list[str]) -> str:
    """The chat template a managed server will use, read without starting it.

    `--chat-template-file` from the server's extra args, else the template
    embedded in the GGUF. A builtin `--chat-template NAME` can't be read
    offline, so it yields "" until the server is probed.
    """
    tokens = [t for arg in extra_args for t in shlex.split(arg)]
    for i, tok in enumerate(tokens):
        if tok.startswith("--chat-template-file"):
            path = tok.partition("=")[2] or (tokens[i + 1] if i + 1 < len(tokens) else "")
            try:
                return Path(path).read_text(errors="replace")
            except OSError:
                return ""
        if tok == "--chat-template" or tok.startswith("--chat-template="):
            return ""
    return (read_chat_template(model_path) or "") if model_path else ""


def template_reasoning_efforts(model_path: str | None, extra_args: list[str]) -> list[str]:
    """Reasoning efforts a managed server will support, without starting it."""
    return _infer_reasoning_efforts(server_chat_template(model_path, extra_args))


def _pick_upstream_model(models: list[dict], configured_name: str) -> dict | None:
    if not models:
        return None
    for model in models:
        if model.get("id") == configured_name:
            return model
    return models[0]


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _extract_props_context_length(payload: dict[str, Any], parallel: int = 1) -> int | None:
    """Extract per-slot context length from llama-server's /props payload.

    llama-server reports n_ctx as the TOTAL context budget (ctx_size × parallel),
    not the per-slot value. We divide by parallel to recover the per-slot context.
    """
    direct = _coerce_int(payload.get("n_ctx"))
    if direct is None:
        dgs = payload.get("default_generation_settings")
        if isinstance(dgs, dict):
            direct = _coerce_int(dgs.get("n_ctx"))
    if direct is None:
        return None
    # If the payload reports n_parallel, prefer it (handles remote servers
    # where we don't know the configured parallel count).
    n_parallel = _coerce_int(payload.get("n_parallel")) or parallel
    if n_parallel > 1 and direct % n_parallel == 0:
        return direct // n_parallel
    return direct


_DEFAULT_CONTEXT_LENGTH = 4096


async def probe_one(srv: SubserverConfig, client: httpx.AsyncClient) -> None:
    """Probe a single subserver and backfill its metadata in place."""
    props_ctx: int | None = None
    srv.reachable = False

    try:
        r_props = await client.get(f"{srv.url}/props", timeout=_PROBE_TIMEOUT)
        if r_props.status_code == 200:
            srv.reachable = True
            props_payload = r_props.json()
            if isinstance(props_payload, dict):
                props_ctx = _extract_props_context_length(props_payload, srv.parallel)
                # Vision capability: llama-server reports modalities.vision when a
                # multimodal projector (mmproj) is loaded.
                modalities = props_payload.get("modalities")
                if isinstance(modalities, dict):
                    srv.vision = bool(modalities.get("vision"))
                    srv.vision_known = True
                # Infer which reasoning-effort values the chat template supports.
                chat_template = props_payload.get("chat_template") or ""
                srv.supported_reasoning_efforts = _infer_reasoning_efforts(chat_template)
                srv.default_reasoning_effort = _infer_default_effort(chat_template)
                srv.thinking = bool(srv.supported_reasoning_efforts) or any(
                    marker in chat_template for marker in _THINKING_MARKERS
                )
                caps = props_payload.get("chat_template_caps")
                if isinstance(caps, dict) and "supports_tools" in caps:
                    srv.tools = bool(caps["supports_tools"])
    except (httpx.ConnectError, httpx.TimeoutException, ValueError):
        pass

    try:
        r_models = await client.get(f"{srv.url}/v1/models", timeout=_PROBE_TIMEOUT)
        if r_models.status_code == 200:
            srv.reachable = True
            models = r_models.json().get("data", [])
            selected = _pick_upstream_model(models, srv.name)
            if selected:
                meta = selected.get("meta", {}) or {}
                srv.upstream_model_id = selected.get("id", srv.name)
                srv.upstream_meta = meta

                if srv.size == 0:
                    size = _coerce_int(selected.get("size")) or _coerce_int(meta.get("size"))
                    if size is not None:
                        srv.size = size

                if not srv.parameter_size:
                    n_params = _coerce_int(meta.get("n_params"))
                    if n_params is not None:
                        srv.parameter_size = f"{round(n_params / 1e9, 1)}B"

                # Only update context_length if it wasn't explicitly set in config
                if srv.context_length == _DEFAULT_CONTEXT_LENGTH:
                    ctx = (
                        props_ctx
                        or _coerce_int(meta.get("n_ctx"))
                        or _coerce_int(meta.get("context_length"))
                        or _coerce_int(meta.get("n_ctx_train"))
                    )
                    if ctx is not None:
                        srv.context_length = ctx

                # llama-server reports the GGUF file type (e.g. "Q8_0") as ftype.
                srv.quantization = str(meta.get("ftype") or "")

    except (httpx.ConnectError, httpx.TimeoutException):
        pass


async def probe_subservers() -> None:
    """Query all subservers and backfill missing metadata."""
    from ..http_client import shared_client

    async with shared_client() as client:
        for srv in get_all_subservers():
            await probe_one(srv, client)
