"""Reasoning controls shared by every gateway surface (Ollama, OpenAI, llama.cpp).

llama-server ignores a top-level `reasoning_effort`; the chat template only sees
values passed through `chat_template_kwargs`. Likewise, the template only renders
past thinking from `message.reasoning_content`, while clients variously send it
back as `reasoning`, `thinking` or `reasoning_details`. This module normalizes
both before a request goes upstream.
"""

from __future__ import annotations

from typing import Any

from .registry import split_virtual_model

# Effort → (template reasoning_effort, reasoning_budget). high = unrestricted (-1).
# Templates such as Qwen 3.x accept low / medium / high / xhigh.
_REASONING_EFFORT_MAP: dict[str, tuple[str, int]] = {
    "minimal": ("low", 1024),
    "low": ("low", 1024),
    "medium": ("medium", 4096),
    "high": ("high", -1),
    "xhigh": ("xhigh", -1),
}

# Values that disable thinking. Passing "none" as reasoning_effort makes some
# templates raise, so these map to enable_thinking=false instead.
_DISABLED_EFFORTS = {"none", "0", "false", "off"}

# Alternate names clients use for an assistant message's thinking.
_REASONING_ALIASES = ("reasoning", "thinking")


def _extract_reasoning_effort(body: dict[str, Any]) -> str | None:
    """Pull a reasoning effort from the request body.

    Sources, in priority order:
    - top-level `reasoning_effort` (OpenAI chat completions)
    - `reasoning.effort` (OpenAI Responses / OpenRouter)
    - `options.reasoning_effort`
    - `think` (Ollama: bool or "low"/"medium"/"high")
    """
    top = body.get("reasoning_effort")
    if top is not None:
        return str(top).lower()
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("effort") is not None:
        return str(reasoning["effort"]).lower()
    options = body.get("options")
    if isinstance(options, dict) and options.get("reasoning_effort") is not None:
        return str(options["reasoning_effort"]).lower()
    think = body.get("think")
    if think is False:
        return "none"
    if isinstance(think, str):
        return think.lower()
    return None


def _extract_preserve_thinking(body: dict[str, Any]) -> bool | None:
    """Pull a `preserve_thinking` flag from the top level or `options`."""
    val = body.get("preserve_thinking")
    if val is None:
        options = body.get("options")
        if isinstance(options, dict):
            val = options.get("preserve_thinking")
    return None if val is None else bool(val)


def _apply_reasoning_effort(payload: dict[str, Any], body: dict[str, Any], model_name: str | None = None) -> None:
    """Map a client reasoning effort onto the llama-server payload.

    The virtual model suffix (e.g. "name:high") wins over any body value.
    Sets `reasoning_budget` and `chat_template_kwargs` (the only place the
    template reads the effort from).
    """
    raw = None
    if model_name:
        _, raw = split_virtual_model(model_name)
    if raw is None:
        raw = _extract_reasoning_effort(body)
    if raw is None:
        return
    kwargs = dict(payload.get("chat_template_kwargs") or {})
    payload.pop("reasoning_effort", None)
    if raw in _DISABLED_EFFORTS:
        kwargs.pop("reasoning_effort", None)
        kwargs["enable_thinking"] = False
        payload["reasoning_budget"] = 0
    else:
        # Unknown values pass through so templates can accept model-specific efforts.
        effort, budget = _REASONING_EFFORT_MAP.get(raw, (raw, -1))
        kwargs["reasoning_effort"] = effort
        payload["reasoning_budget"] = budget
    payload["chat_template_kwargs"] = kwargs


def _normalize_message_reasoning(message: dict[str, Any]) -> None:
    """Move an assistant message's thinking into `reasoning_content`."""
    if message.get("role") != "assistant":
        return
    aliases = {k: message.pop(k) for k in _REASONING_ALIASES if k in message}
    details = message.pop("reasoning_details", None)
    if isinstance(message.get("reasoning_content"), str):
        return
    for value in aliases.values():
        if isinstance(value, str) and value:
            message["reasoning_content"] = value
            return
    if isinstance(details, list):
        text = "".join(d.get("text", "") for d in details if isinstance(d, dict))
        if text:
            message["reasoning_content"] = text


def apply_reasoning(payload: dict[str, Any], body: dict[str, Any], model_name: str | None = None) -> None:
    """Normalize effort, preserve_thinking and past thinking for a chat payload."""
    _apply_reasoning_effort(payload, body, model_name)
    payload.pop("reasoning", None)
    preserve = _extract_preserve_thinking(body)
    payload.pop("preserve_thinking", None)
    if preserve is not None:
        kwargs = dict(payload.get("chat_template_kwargs") or {})
        kwargs["preserve_thinking"] = preserve
        payload["chat_template_kwargs"] = kwargs
    for message in payload.get("messages") or []:
        if isinstance(message, dict):
            _normalize_message_reasoning(message)
