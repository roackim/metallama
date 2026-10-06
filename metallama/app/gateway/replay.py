"""Reasoning replay: getting a client's stored reasoning back into the prompt.

Chat templates disagree on what to do with the reasoning of earlier assistant
turns (Qwen3.x: `preserve_thinking`; GLM: `clear_thinking`; others:
`truncate_history_thinking`, `drop_thinking`), and by default most strip it
from every turn before the last user message. llama.cpp unifies these behind
one template kwarg, `preserve_reasoning` (what `--reasoning-preserve` sets;
`/props` reports `chat_template_caps.supports_preserve_reasoning`). It sets all
the aliases consistently and is a no-op on templates without the capability.
Two jobs here:

- normalize every dialect's assistant reasoning field to `reasoning_content`,
  the only one llama-server reads;
- when the history carries reasoning, turn `preserve_reasoning` on in
  `chat_template_kwargs` (never overriding the client).

The *depth* (how many turns carry reasoning) stays the client's decision:
turns it sends without reasoning render as the template renders them empty.
"""
from __future__ import annotations

from typing import Any


def _details_text(details: Any) -> str:
    """Plain text of OpenRouter `reasoning_details` (encrypted blocks have none)."""
    if not isinstance(details, list):
        return ""
    parts = []
    for d in details:
        if isinstance(d, dict):
            text = d.get("text") or d.get("summary")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def normalize_history_reasoning(messages: Any) -> None:
    """Move assistant reasoning to `reasoning_content`, dropping the aliases.

    Aliases: OpenRouter `reasoning` / `reasoning_details`, Ollama `thinking`.
    An existing `reasoning_content` string wins.
    """
    if not isinstance(messages, list):
        return
    for m in messages:
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        alias_text = ""
        for key in ("reasoning", "thinking"):
            val = m.pop(key, None)
            if not alias_text and isinstance(val, str):
                alias_text = val
        details = _details_text(m.pop("reasoning_details", None))
        if not isinstance(m.get("reasoning_content"), str):
            text = alias_text or details
            if text:
                m["reasoning_content"] = text
            else:
                m.pop("reasoning_content", None)


def has_history_reasoning(messages: Any) -> bool:
    return isinstance(messages, list) and any(
        isinstance(m, dict)
        and m.get("role") == "assistant"
        and isinstance(m.get("reasoning_content"), str)
        and m["reasoning_content"].strip()
        for m in messages
    )


# OpenAI's `reasoning.context` (also OpenRouter's) -> preserve_reasoning.
# "auto" / absent leave the decision to the history (see _decide).
_CONTEXT_KEEP = {"all_turns": True, "current_turn": False}


def _explicit_keep(body: dict[str, Any]) -> bool | None:
    """The client's stated intent, popping the non-standard top-level switches.

    Precedence (first found wins): `chat_template_kwargs.preserve_reasoning` is
    left alone by the caller; then top-level `preserve_reasoning` /
    `preserve_thinking` / `clear_thinking`; then the standard
    `reasoning.context`.
    """
    explicit: bool | None = None
    for key in ("preserve_reasoning", "preserve_thinking"):
        if isinstance(body.get(key), bool) and explicit is None:
            explicit = body[key]
        body.pop(key, None)
    if isinstance(body.get("clear_thinking"), bool) and explicit is None:
        explicit = not body["clear_thinking"]
    body.pop("clear_thinking", None)
    if explicit is None:
        reasoning = body.get("reasoning")
        if isinstance(reasoning, dict):
            explicit = _CONTEXT_KEEP.get(reasoning.get("context"))
    return explicit


def _set_flag(body: dict[str, Any], has_reasoning: bool) -> None:
    keep = _explicit_keep(body)
    if keep is None:
        if not has_reasoning:
            return
        keep = True
    kwargs = body.get("chat_template_kwargs")
    if not isinstance(kwargs, dict):
        kwargs = {}
    kwargs.setdefault("preserve_reasoning", keep)
    body["chat_template_kwargs"] = kwargs


def apply_replay(body: dict[str, Any]) -> None:
    """Chat Completions: make the template keep the reasoning the client sent.

    On when the history carries reasoning, unless the client said otherwise
    (see `_explicit_keep`). Must run before the effort step, which consumes
    the `reasoning` object.
    """
    normalize_history_reasoning(body.get("messages"))
    _set_flag(body, has_history_reasoning(body.get("messages")))


def _item_text(item: dict[str, Any]) -> str:
    """Plaintext of a Responses reasoning item: `content` text, else `summary` text.

    Encrypted-only items (cloud models' opaque reasoning) have none.
    """
    for key in ("content", "summary"):
        parts = item.get(key)
        if isinstance(parts, list):
            text = "".join(
                p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)
            )
            if text.strip():
                return text
    return ""


def apply_replay_responses(body: dict[str, Any]) -> None:
    """Responses API: same job on `input` items.

    llama-server only accepts reasoning items shaped like its own output
    (`summary` array plus `content[0].text`) and rejects anything else with a
    400, so items are rewritten to that shape, and items without plaintext
    are dropped.
    """
    items = body.get("input")
    has_reasoning = False
    if isinstance(items, list):
        kept = []
        for item in items:
            if isinstance(item, dict) and item.get("type") == "reasoning":
                text = _item_text(item)
                if not text:
                    continue
                item = {
                    "type": "reasoning",
                    "summary": [],
                    "content": [{"type": "reasoning_text", "text": text}],
                }
                has_reasoning = True
            kept.append(item)
        body["input"] = kept
    _set_flag(body, has_reasoning)
