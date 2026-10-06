"""Reasoning effort, applied the way llama-server's chat templates read it.

Which effort a request asks for (and whether the server allows it) is decided by
`registry.resolve_reasoning_effort`. This module turns that decision into the
upstream payload: llama-server ignores a top-level `reasoning_effort` (and maps
nothing to `enable_thinking`), so the effort goes into `chat_template_kwargs`,
the only place templates read it from. Past reasoning in the history is handled
separately by `replay`.
"""

from __future__ import annotations

from typing import Any

from .registry import resolve_reasoning_effort
from .replay import apply_replay
from .schemas import SubserverConfig

# Request fields that select an effort; consumed here, never sent upstream.
_EFFORT_FIELDS = ("think", "reasoning", "reasoning_effort")


def _template_effort(effort: str, supported: list[str]) -> str:
    """The value to hand the template for a requested effort.

    `minimal` and `max` are vocabulary of other APIs (OpenRouter, Ollama); when
    the template doesn't know them, use its lowest / highest supported level
    instead of letting the template reject the request.
    """
    levels = [e for e in supported if e != "none"]
    if effort in supported or not levels:
        return effort
    if effort == "minimal":
        return levels[0]
    if effort == "max":
        return levels[-1]
    return effort


def apply_effort(payload: dict[str, Any], srv: SubserverConfig, model_name: str, body: dict[str, Any]) -> None:
    """Resolve the request's effort (400 if not allowed) and set it on `payload`.

    `body` is what the client sent (it may differ from `payload`, e.g. Ollama's
    request vs the translated chat payload). With no effort requested, the
    template's default applies.
    """
    effort = resolve_reasoning_effort(srv, model_name, body)
    for field in _EFFORT_FIELDS:
        payload.pop(field, None)
    if effort is None:
        return
    kwargs = payload.get("chat_template_kwargs")
    kwargs = dict(kwargs) if isinstance(kwargs, dict) else {}
    if effort == "none":
        kwargs.pop("reasoning_effort", None)
        kwargs["enable_thinking"] = False
    else:
        kwargs["reasoning_effort"] = _template_effort(effort, srv.supported_reasoning_efforts)
    payload["chat_template_kwargs"] = kwargs


def apply_reasoning(payload: dict[str, Any], srv: SubserverConfig, model_name: str, body: dict[str, Any]) -> None:
    """Chat payloads: replay the history's reasoning, then apply the effort.

    Replay runs first: it reads `reasoning.context`, which the effort step consumes.
    """
    apply_replay(payload)
    apply_effort(payload, srv, model_name, body)
