"""Live contract checks for every metallama gateway (/openai, /ollama/v1, /openrouter, /ollama).

Run against a running metallama with a model server up:

    python tests/gateway_contract.py [--base http://127.0.0.1:8010] [--model NAME]

Stdlib only. Each check prints PASS/FAIL; the exit code is the number of failures.
What each gateway must honour is described in .wiki/notes/api.md.
"""
from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
import urllib.error
import urllib.request
import zlib

FAILS: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"   -> {detail}"))
    if not ok:
        FAILS.append(name)
    return ok


def call(base: str, path: str, body: dict | None = None, method: str | None = None, raw: bool = False):
    """(status, parsed JSON | raw text, headers)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if body is not None else "GET"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            text = r.read().decode()
            status, headers = r.status, r.headers
    except urllib.error.HTTPError as e:
        text, status, headers = e.read().decode(), e.code, e.headers
    if raw:
        return status, text, headers
    try:
        return status, json.loads(text), headers
    except ValueError:
        return status, text, headers


def has_null(x: object, path: str = "") -> str | None:
    if x is None:
        return path or "<root>"
    if isinstance(x, dict):
        for k, v in x.items():
            if (r := has_null(v, f"{path}.{k}")):
                return r
    if isinstance(x, list):
        for i, v in enumerate(x):
            if (r := has_null(v, f"{path}[{i}]")):
                return r
    return None


def sse(text: str) -> tuple[list[dict], list[str], bool]:
    """(JSON chunks, comment lines, saw [DONE]); fails on malformed framing."""
    chunks, comments, done = [], [], False
    for line in text.split("\n"):
        if not line:
            continue
        if line.startswith(":"):
            comments.append(line)
        elif line.startswith("data:"):
            payload = line[5:].strip()
            if payload == "[DONE]":
                done = True
            else:
                chunks.append(json.loads(payload))
        elif line.startswith("event:"):
            pass
        else:
            raise ValueError(f"not SSE: {line[:80]!r}")
    return chunks, comments, done


def png_data_url() -> str:
    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    w = h = 32
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


TOOL = {"type": "function", "function": {
    "name": "get_weather", "description": "Get the current weather for a city.",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}


def history(reasoning_key: str, text: str) -> list[dict]:
    return [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1", reasoning_key: text},
            {"role": "user", "content": "Q2"}, {"role": "assistant", "content": "A2", reasoning_key: text},
            {"role": "user", "content": "Say ok."}]


# ---------------------------------------------------------------------------
# OpenAI-shaped gateways
# ---------------------------------------------------------------------------


def check_models(base: str, prefix: str, model: str, openrouter: bool) -> None:
    st, d, _ = call(base, f"{prefix}/models")
    check(f"{prefix}/models 200 with data[]", st == 200 and isinstance(d, dict) and d.get("data"), st)
    data = d["data"] if isinstance(d, dict) else []
    check(f"{prefix}/models ids unique", len({m["id"] for m in data}) == len(data))
    check(f"{prefix}/models context_length on every entry",
          all(isinstance(m.get("context_length"), int) and m["context_length"] > 0 for m in data))
    check(f"{prefix}/models no null values (clients store TOML)", has_null(data) is None, has_null(data))
    check(f"{prefix}/models lists {model}", any(m["id"] == model for m in data))
    if not openrouter:
        check(f"{prefix}/models architecture.input_modalities agrees with meta.vision",
              all(isinstance(m.get("architecture", {}).get("input_modalities"), list)
                  and ("image" in m["architecture"]["input_modalities"]) == bool(m["meta"].get("vision"))
                  for m in data), [(m["id"], m.get("architecture"), m["meta"].get("vision")) for m in data])
    if openrouter:
        need = ["id", "canonical_slug", "name", "created", "description", "context_length", "architecture",
                "pricing", "top_provider", "supported_parameters", "links"]
        check(f"{prefix}/models OpenRouter required fields", all(all(k in m for k in need) for m in data),
              [k for k in need if data and k not in data[0]])
    for m in data:
        r = m.get("reasoning")
        if r:
            check(f"{prefix}/models reasoning.supported_efforts is a list of strings",
                  isinstance(r.get("supported_efforts"), list))
            break


def check_stream(base: str, prefix: str, model: str, openrouter: bool) -> None:
    body = {"model": model, "stream": True, "reasoning_effort": "low", "max_tokens": 400,
            "messages": [{"role": "user", "content": "What is 2+2? Answer in one word."}]}
    st, text, hd = call(base, f"{prefix}/chat/completions", body, raw=True)
    check(f"{prefix} stream: 200 + text/event-stream", st == 200 and "text/event-stream" in hd.get("content-type", ""), (st, hd.get("content-type")))
    try:
        chunks, _, done = sse(text)
    except ValueError as e:
        check(f"{prefix} stream: well-formed SSE", False, e)
        return
    check(f"{prefix} stream: well-formed SSE ending with [DONE]", done)
    check(f"{prefix} stream: finish_reason on a choice",
          any(c.get("choices") and c["choices"][0].get("finish_reason") for c in chunks))
    last = chunks[-1] if chunks else {}
    u = last.get("usage") or {}
    check(f"{prefix} stream: last chunk is usage with empty choices",
          last.get("choices") == [] and all(isinstance(u.get(k), int) for k in ("prompt_tokens", "completion_tokens", "total_tokens")), last)
    deltas = [c["choices"][0].get("delta", {}) for c in chunks if c.get("choices")]
    field = "reasoning" if openrouter else "reasoning_content"
    other = "reasoning_content" if openrouter else "reasoning"
    check(f"{prefix} stream: reasoning in delta.{field}", any(d.get(field) for d in deltas))
    check(f"{prefix} stream: no delta.{other}", not any(other in d for d in deltas))
    check(f"{prefix} stream: answer in delta.content", any(d.get("content") for d in deltas))
    check(f"{prefix} stream: `model` echoes the requested id on every chunk (not the GGUF path)",
          all(c.get("model") == model for c in chunks), sorted({str(c.get("model")) for c in chunks}))


def check_nonstream(base: str, prefix: str, model: str, openrouter: bool) -> None:
    st, d, _ = call(base, f"{prefix}/chat/completions", {"model": model, "reasoning_effort": "low", "max_tokens": 400,
                    "messages": [{"role": "user", "content": "What is 2+2? One word."}]})
    ok = st == 200 and isinstance(d, dict)
    check(f"{prefix} non-stream: 200 with usage", ok and isinstance(d.get("usage", {}).get("total_tokens"), int), (st, d))
    msg = d["choices"][0]["message"] if ok else {}
    field = "reasoning" if openrouter else "reasoning_content"
    check(f"{prefix} non-stream: message.{field}", bool(msg.get(field)), list(msg))
    check(f"{prefix} non-stream: answer content", bool(msg.get("content")))
    check(f"{prefix} non-stream: `model` echoes the requested id", d.get("model") == model, d.get("model"))


def check_tools(base: str, prefix: str, model: str) -> None:
    body = {"model": model, "stream": True, "reasoning_effort": "low", "max_tokens": 800, "tools": [TOOL],
            "messages": [{"role": "user", "content": "What's the weather in Paris? Use the tool."}]}
    st, text, _ = call(base, f"{prefix}/chat/completions", body, raw=True)
    chunks, _, done = sse(text) if st == 200 else ([], [], False)
    calls: dict[int, dict] = {}
    fin = None
    for c in chunks:
        for ch in c.get("choices") or []:
            fin = ch.get("finish_reason") or fin
            for tc in ch.get("delta", {}).get("tool_calls") or []:
                slot = calls.setdefault(tc.get("index", 0), {"id": None, "name": "", "args": ""})
                slot["id"] = tc.get("id") or slot["id"]
                f = tc.get("function") or {}
                slot["name"] += f.get("name") or ""
                a = f.get("arguments")
                slot["args"] += a if isinstance(a, str) else json.dumps(a or "")
    ok = bool(calls)
    check(f"{prefix} tools: streamed tool_calls with finish_reason=tool_calls", ok and fin == "tool_calls", (st, fin, calls))
    if not ok:
        return
    tc = calls[0]
    try:
        args = json.loads(tc["args"])
    except ValueError:
        args = None
    check(f"{prefix} tools: name + JSON arguments assemble", tc["name"] == "get_weather" and isinstance(args, dict), tc)
    follow = body["messages"] + [
        {"role": "assistant", "content": "", "reasoning_content": "I should call the tool.",
         "tool_calls": [{"id": tc["id"] or "call_0", "type": "function",
                         "function": {"name": "get_weather", "arguments": tc["args"]}}]},
        {"role": "tool", "tool_call_id": tc["id"] or "call_0", "content": "18C and sunny"}]
    st, d, _ = call(base, f"{prefix}/chat/completions", {**body, "stream": False, "messages": follow})
    check(f"{prefix} tools: tool result round trip (tool_call_id + reasoning_content)", st == 200, (st, d))


def check_image(base: str, prefix: str, model: str) -> None:
    body = {"model": model, "reasoning_effort": "low", "max_tokens": 300, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "What color is this image? One word."},
        {"type": "image_url", "image_url": {"url": png_data_url()}}]}]}
    st, d, _ = call(base, f"{prefix}/chat/completions", body)
    check(f"{prefix} image content part (base64 data URL)", st == 200, (st, str(d)[:200]))


def check_replay(base: str, prefix: str, model: str, openrouter: bool) -> None:
    key = "reasoning" if openrouter else "reasoning_content"
    text = "ALPHA " * 40

    def tokens(extra: dict, h: list[dict]) -> int | None:
        eff = {"reasoning": {"effort": "low", **extra.pop("reasoning", {})}} if openrouter else {"reasoning_effort": "low"}
        st, d, _ = call(base, f"{prefix}/chat/completions", {"model": model, "max_tokens": 4, "messages": h, **eff, **extra})
        return d.get("usage", {}).get("prompt_tokens") if st == 200 else None

    auto = tokens({}, history(key, text))
    allt = tokens({"reasoning": {"context": "all_turns"}}, history(key, text)) if openrouter else \
        tokens({"reasoning": {"context": "all_turns"}}, history(key, text))
    cur = tokens({"reasoning": {"context": "current_turn"}}, history(key, text))
    empty = tokens({}, history(key, ""))
    check(f"{prefix} replay: history reasoning reaches the prompt (auto > empty)", auto and empty and auto > empty, (auto, empty))
    check(f"{prefix} replay: reasoning.context all_turns == auto", auto == allt, (auto, allt))
    check(f"{prefix} replay: reasoning.context current_turn strips history", cur and empty and cur < auto, (cur, auto))


def check_effort(base: str, prefix: str, model: str, openrouter: bool) -> None:
    """The effort must actually reach the template (llama-server ignores a top-level one)."""
    key = "reasoning" if openrouter else "reasoning_content"
    msgs = [{"role": "user", "content": "What is 17*23? Answer only the number."}]
    st, d, _ = call(base, f"{prefix}/chat/completions", {"model": model, "messages": msgs, "reasoning_effort": "none"})
    msg = d.get("choices", [{}])[0].get("message", {}) if isinstance(d, dict) else {}
    check(f"{prefix} effort: reasoning_effort none -> no reasoning", st == 200 and not msg.get(key), (st, msg))
    st, d, _ = call(base, f"{prefix}/chat/completions", {"model": model, "messages": msgs, "reasoning_effort": "low"})
    msg = d.get("choices", [{}])[0].get("message", {}) if isinstance(d, dict) else {}
    check(f"{prefix} effort: reasoning_effort low -> reasoning", st == 200 and bool(msg.get(key)), (st, str(msg)[:200]))


def check_errors(base: str, prefix: str, model: str) -> None:
    st, d, _ = call(base, f"{prefix}/chat/completions", {"model": "nope", "messages": [{"role": "user", "content": "x"}]})
    check(f"{prefix} errors: unknown model -> 404 with error.message",
          st == 404 and isinstance(d, dict) and isinstance(d.get("error", {}).get("message"), str), (st, d))
    st, d, _ = call(base, f"{prefix}/chat/completions", {"model": model, "reasoning_effort": "bogus",
                    "messages": [{"role": "user", "content": "x"}]})
    check(f"{prefix} errors: disallowed effort -> 400 listing allowed", st == 400 and "allowed_efforts" in d.get("error", {}), (st, d))
    req = urllib.request.Request(base + f"{prefix}/chat/completions", data=b"not json", method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30)
        st = 200
    except urllib.error.HTTPError as e:
        st = e.code
    check(f"{prefix} errors: non-JSON body -> 400", st == 400, st)


def check_openrouter_extras(base: str, model: str) -> None:
    p = "/openrouter/v1"
    body = {"model": model, "stream": True, "max_tokens": 300, "messages": [{"role": "user", "content": "2+2? one word"}]}
    for label, extra in [("reasoning.exclude", {"reasoning": {"effort": "low", "exclude": True}}),
                         ("include_reasoning:false", {"reasoning": {"effort": "low"}, "include_reasoning": False})]:
        st, text, _ = call(base, f"{p}/chat/completions", {**body, **extra}, raw=True)
        chunks, _, _ = sse(text) if st == 200 else ([], [], False)
        deltas = [c["choices"][0].get("delta", {}) for c in chunks if c.get("choices")]
        check(f"{p} {label}: no reasoning in stream", st == 200 and not any(d.get("reasoning") or d.get("reasoning_content") for d in deltas), st)
    st, d, _ = call(base, f"{p}/chat/completions", {**body, "stream": False, "provider": {"order": ["x"]}, "route": "fallback",
                    "reasoning": {"effort": "low"}})
    check(f"{p} OpenRouter-only fields (provider, route) are tolerated", st == 200, (st, d))


def check_responses(base: str, prefix: str, model: str) -> None:
    st, d, _ = call(base, f"{prefix}/responses", {"model": model, "input": "2+2? one word", "max_output_tokens": 300,
                    "reasoning": {"effort": "low"}})
    check(f"{prefix} responses: 200 with output[]", st == 200 and isinstance(d, dict) and d.get("output"), (st, str(d)[:200]))
    st, text, hd = call(base, f"{prefix}/responses", {"model": model, "input": "hi", "stream": True, "max_output_tokens": 50,
                        "reasoning": {"effort": "low"}}, raw=True)
    check(f"{prefix} responses: stream is event-stream and completes", st == 200 and "response.completed" in text, st)
    models = {c.get("model") or (c.get("response") or {}).get("model") for c in sse(text)[0]} - {None}
    check(f"{prefix} responses: stream `model` echoes the requested id", models == {model}, models)
    st, d, _ = call(base, f"{prefix}/responses", {"model": model, "input": "hi", "previous_response_id": "resp_x"})
    check(f"{prefix} responses: previous_response_id -> 400", st == 400, (st, d))
    # Reasoning items in input: sparse/encrypted-only items must not 400.
    items = [{"type": "message", "role": "user", "content": "Q1"},
             {"type": "reasoning", "id": "rs1", "summary": [{"type": "summary_text", "text": "ALPHA " * 40}], "encrypted_content": "z"},
             {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "A1"}]},
             {"type": "reasoning", "id": "rs2", "summary": [], "encrypted_content": "opaque"},
             {"type": "message", "role": "user", "content": "Say ok."}]

    def tokens(extra: dict) -> int | None:
        st, d, _ = call(base, f"{prefix}/responses", {"model": model, "input": items, "max_output_tokens": 4,
                        "reasoning": {"effort": "low", **extra}})
        return d.get("usage", {}).get("input_tokens") if st == 200 else None

    allt, cur = tokens({"context": "all_turns"}), tokens({"context": "current_turn"})
    check(f"{prefix} responses: reasoning items accepted; current_turn strips them", allt and cur and cur < allt, (allt, cur))


def check_other_endpoints(base: str, prefix: str, model: str) -> None:
    st, d, _ = call(base, f"{prefix}/completions", {"model": model, "prompt": "1+1=", "max_tokens": 4})
    check(f"{prefix} completions: 200", st == 200 and d.get("choices"), (st, str(d)[:200]))
    st, d, _ = call(base, f"{prefix}/embeddings", {"model": model, "input": "hello"})
    check(f"{prefix} embeddings: reachable (200, or upstream's own status preserved)", st in (200, 400, 404, 500, 501), st)


def check_no_props(base: str) -> None:
    for p in ("/props", "/openai/props", "/openai/v1/props", "/openrouter/props", "/openrouter/v1/props", "/ollama/v1/props"):
        st, _, _ = call(base, p)
        check(f"no {p} (would override per-model facts in clients)", st == 404, st)


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


def ndjson(text: str) -> list[dict]:
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def check_ollama(base: str, model: str) -> None:
    o = "/ollama/api"
    st, d, _ = call(base, f"{o}/tags")
    m = next((x for x in d.get("models", []) if x.get("name") == model), None) if isinstance(d, dict) else None
    check("ollama /api/tags lists the model with details", st == 200 and m and all(k in m for k in ("name", "model", "size", "details")), (st, m))
    check("ollama /api/tags no null values", has_null(d) is None, has_null(d))
    st, d, _ = call(base, f"{o}/show", {"model": model})
    caps = d.get("capabilities", []) if isinstance(d, dict) else []
    check("ollama /api/show: capabilities has completion + thinking + tools",
          st == 200 and {"completion", "thinking", "tools"} <= set(caps), (st, caps))
    check("ollama /api/show: model_info + details", st == 200 and "model_info" in d and "details" in d, list(d) if isinstance(d, dict) else d)
    st, d, _ = call(base, f"{o}/ps")
    check("ollama /api/ps: models[]", st == 200 and "models" in d, (st, d))
    st, d, _ = call(base, f"{o}/version")
    check("ollama /api/version", st == 200 and isinstance(d.get("version"), str), (st, d))

    body = {"model": model, "think": "low", "options": {"num_predict": 400},
            "messages": [{"role": "user", "content": "What is 2+2? One word."}]}
    st, text, hd = call(base, f"{o}/chat", {**body, "stream": True}, raw=True)
    lines = ndjson(text) if st == 200 else []
    check("ollama chat stream: NDJSON, last line done:true", bool(lines) and lines[-1].get("done") is True, (st, text[:200]))
    last = lines[-1] if lines else {}
    check("ollama chat stream: done_reason + counts + durations",
          last.get("done_reason") in ("stop", "length") and isinstance(last.get("prompt_eval_count"), int)
          and isinstance(last.get("eval_count"), int) and "total_duration" in last, last)
    msgs = [x.get("message", {}) for x in lines]
    check("ollama chat stream: message.thinking then message.content",
          any(m.get("thinking") for m in msgs) and any(m.get("content") for m in msgs), msgs[:3])
    check("ollama chat stream: every line has model + created_at + message role=assistant",
          all(x.get("model") and x.get("created_at") and x.get("message", {}).get("role") == "assistant" for x in lines), lines[:1])
    st, d, _ = call(base, f"{o}/chat", {**body, "stream": False})
    check("ollama chat non-stream: message.thinking + content + done", st == 200 and d.get("message", {}).get("thinking")
          and d["message"].get("content") and d.get("done") is True, (st, str(d)[:200]))
    st, d, _ = call(base, f"{o}/chat", {**body, "stream": False, "think": "max"})
    check("ollama chat: think level 'max' is recognised (200, or a 400 naming allowed levels)",
          st == 200 or (st == 400 and "allowed" in json.dumps(d)), (st, d))
    st, d, _ = call(base, f"{o}/chat", {**body, "stream": False, "think": False})
    check("ollama chat: think:false -> no thinking, or clear 400 when thinking is mandatory",
          (st == 200 and not d["message"].get("thinking")) or st == 400, (st, str(d)[:200]))
    st, d, _ = call(base, f"{o}/chat", {"model": "nope", "messages": [{"role": "user", "content": "x"}]})
    check("ollama chat: unknown model -> 404 {\"error\": str} (Ollama clients read the top-level error)",
          st == 404 and isinstance(d, dict) and isinstance(d.get("error"), str), (st, d))
    st, d, _ = call(base, f"{o}/chat", {"model": model})
    check("ollama chat: invalid request -> 400 {\"error\": str}", st == 400 and isinstance(d, dict) and isinstance(d.get("error"), str), (st, d))
    st, d, _ = call(base, f"{o}/show", {"model": "nope"})
    check("ollama show: unknown model -> 404 {\"error\": str}", st == 404 and isinstance(d, dict) and isinstance(d.get("error"), str), (st, d))

    # tools: arguments must be a dict, tool_calls on a message, round trip via tool_name
    tbody = {"model": model, "think": "low", "stream": False, "options": {"num_predict": 800}, "tools": [TOOL],
             "messages": [{"role": "user", "content": "What's the weather in Paris? Use the tool."}]}
    st, d, _ = call(base, f"{o}/chat", tbody)
    tcs = d.get("message", {}).get("tool_calls") if st == 200 else None
    check("ollama chat tools: tool_calls[].function.arguments is an object", bool(tcs) and isinstance(tcs[0]["function"]["arguments"], dict), (st, str(d)[:300]))
    if tcs:
        follow = tbody["messages"] + [dict(d["message"]), {"role": "tool", "tool_name": "get_weather", "content": "18C and sunny"}]
        st, d2, _ = call(base, f"{o}/chat", {**tbody, "messages": follow})
        check("ollama chat tools: tool result round trip (thinking + tool_name)", st == 200 and d2.get("message", {}).get("content"), (st, str(d2)[:300]))

    # images: raw base64 in `images`
    b64 = png_data_url().split(",", 1)[1]
    st, d, _ = call(base, f"{o}/chat", {"model": model, "stream": False, "think": "low", "options": {"num_predict": 300},
                    "messages": [{"role": "user", "content": "What color is this? One word.", "images": [b64]}]})
    check("ollama chat: images[] (raw base64)", st == 200, (st, str(d)[:200]))

    # replay
    def tokens(extra: dict, th: str) -> int | None:
        h = [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1", "thinking": th},
             {"role": "user", "content": "Q2"}, {"role": "assistant", "content": "A2", "thinking": th},
             {"role": "user", "content": "Say ok."}]
        st, d, _ = call(base, f"{o}/chat", {"model": model, "stream": False, "think": "low", "options": {"num_predict": 4}, "messages": h, **extra})
        return d.get("prompt_eval_count") if st == 200 else None

    auto, empty = tokens({}, "ALPHA " * 40), tokens({}, "")
    cur = tokens({"reasoning": {"context": "current_turn"}}, "ALPHA " * 40)
    check("ollama replay: message.thinking in history reaches the prompt", auto and empty and auto > empty, (auto, empty))
    check("ollama replay (extension): reasoning.context current_turn strips", cur and auto and cur < auto, (cur, auto))

    # generate
    st, text, _ = call(base, f"{o}/generate", {"model": model, "prompt": "1+1=", "stream": True, "options": {"num_predict": 6}}, raw=True)
    lines = ndjson(text) if st == 200 else []
    check("ollama generate stream: NDJSON with response + final done", bool(lines) and lines[-1].get("done") is True
          and any("response" in x for x in lines), (st, text[:200]))
    st, d, _ = call(base, f"{o}/generate", {"model": model, "prompt": "1+1=", "stream": False, "options": {"num_predict": 6}})
    check("ollama generate non-stream: response + done + done_reason", st == 200 and "response" in d and d.get("done") and d.get("done_reason"), (st, str(d)[:200]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--model", default="Qwen3.8-27B")
    a = ap.parse_args()
    for prefix, openrouter in (("/openai/v1", False), ("/ollama/v1", False), ("/openrouter/v1", True)):
        print(f"\n=== {prefix}")
        check_models(a.base, prefix, a.model, openrouter)
        check_stream(a.base, prefix, a.model, openrouter)
        check_nonstream(a.base, prefix, a.model, openrouter)
        check_tools(a.base, prefix, a.model)
        check_image(a.base, prefix, a.model)
        check_replay(a.base, prefix, a.model, openrouter)
        check_effort(a.base, prefix, a.model, openrouter)
        check_errors(a.base, prefix, a.model)
        if not openrouter:
            check_responses(a.base, prefix, a.model)
            check_other_endpoints(a.base, prefix, a.model)
    print("\n=== openrouter extras")
    check_openrouter_extras(a.base, a.model)
    print("\n=== /props")
    check_no_props(a.base)
    print("\n=== ollama")
    check_ollama(a.base, a.model)
    print(f"\n{len(FAILS)} failure(s)")
    for f in FAILS:
        print("  -", f)
    return len(FAILS)


if __name__ == "__main__":
    sys.exit(min(main(), 125))
