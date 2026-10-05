"""Offline contract checks for the gateways' failure and timing behaviour.

A fake llama-server (slow, failing, or unreachable) stands in for the model, so no GPU or
running metallama is needed:

    PYTHONPATH=. uv run python tests/gateway_failure_modes.py

Covers: keep-alives while upstream is silent, 503 for an unreachable model server,
upstream error status/message preserved, errors after the early 200 (OpenRouter's
documented shape), usage injection, request translation seen by the upstream.
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

sys.path.insert(0, "tests")
from gateway_contract import FAILS, check, sse  # noqa: E402

PORT = 18999
seen: dict = {}
fake = FastAPI()


@fake.post("/v1/chat/completions")
async def chat(r: Request):
    body = await r.json()
    seen["chat"] = body
    last = body["messages"][-1]["content"] if body.get("messages") else ""
    if last == "slow":
        await asyncio.sleep(1.2)
    if last == "reject":
        return JSONResponse({"error": {"message": "prompt too long", "code": 400}}, status_code=400)
    if last == "slow-reject":
        await asyncio.sleep(1.2)
        return JSONResponse({"error": {"message": "prompt too long", "code": 400}}, status_code=400)

    async def gen():
        yield b'data: {"model":"/weights/x.gguf","choices":[{"delta":{"reasoning_content":"th"}}]}\n\n'
        yield b'data: {"model":"/weights/x.gguf","choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
        if (body.get("stream_options") or {}).get("include_usage"):
            yield b'data: {"model":"/weights/x.gguf","choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5},"timings":{"prompt_ms":5.0,"predicted_ms":7.0}}\n\n'
        yield b"data: [DONE]\n\n"

    if body.get("stream"):
        return StreamingResponse(gen(), media_type="text/event-stream")
    return JSONResponse({"model": "/weights/x.gguf",
                         "choices": [{"message": {"content": "ok", "reasoning_content": "th"}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
                         "timings": {"prompt_ms": 5.0, "predicted_ms": 7.0}})


@fake.get("/health")
async def health():
    return {"status": "ok"}


@fake.post("/v1/completions")
async def completions(r: Request):
    seen["completions"] = await r.json()
    return JSONResponse({"choices": [{"text": "2", "finish_reason": "length"}],
                         "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
                         "timings": {"prompt_ms": 1.0, "predicted_ms": 2.0}})


def main() -> int:
    threading.Thread(target=lambda: uvicorn.run(fake, port=PORT, log_level="error"), daemon=True).start()
    time.sleep(1)

    from metallama.app.ollama import registry
    from metallama.app.ollama.routes import ollama, openai, openrouter
    from metallama.app.ollama.schemas import SubserverConfig

    openai._KEEPALIVE_GRACE, openai._KEEPALIVE_INTERVAL = 0.5, 0.4
    registry._registry["up"] = SubserverConfig(name="up", url=f"http://127.0.0.1:{PORT}")
    registry._registry["down"] = SubserverConfig(name="down", url="http://127.0.0.1:1")
    app = FastAPI()
    app.include_router(openai.router, prefix="/openai")
    app.include_router(openrouter.router, prefix="/openrouter")
    app.include_router(ollama.router, prefix="/ollama")
    c = TestClient(app).__enter__()  # one event loop: the gateway's shared HTTP client is bound to it

    def stream(path: str, model: str, text: str, **extra):
        body = {"model": model, "stream": True, "messages": [{"role": "user", "content": text}], **extra}
        with c.stream("POST", path, json=body) as r:
            return r.status_code, r.read().decode()

    for prefix in ("/openai/v1", "/openrouter/v1"):
        p = f"{prefix}/chat/completions"
        print(f"\n=== {prefix}")
        st, text = stream(p, "up", "slow")
        chunks, comments, done = sse(text)
        check(f"{prefix} keep-alive: 200 + SSE comments while upstream is silent", st == 200 and len(comments) >= 1 and done, (st, text[:120]))
        check(f"{prefix} keep-alive: content arrives intact after the comments", any(
            ch.get("delta", {}).get("content") == "ok" for k in chunks for ch in k.get("choices") or []))
        st, text = stream(p, "up", "hi")
        chunks, _, _ = sse(text)
        check(f"{prefix} stream: `model` is the client's id, not llama-server's GGUF path (incl. usage chunk)",
              chunks and all(k.get("model") == "up" for k in chunks), [k.get("model") for k in chunks])
        r = c.post(p, json={"model": "up", "messages": [{"role": "user", "content": "hi"}]})
        check(f"{prefix} non-stream: `model` is the client's id", r.json().get("model") == "up", r.json().get("model"))
        st, text = stream(p, "up", "slow")
        chunks, _, _ = sse(text)
        check(f"{prefix} after keep-alives: `model` is the client's id", chunks and all(k.get("model") == "up" for k in chunks))
        st, text = stream(p, "up", "hi")
        check(f"{prefix} fast request: no keep-alive noise", st == 200 and ": keepalive" not in text, text[:80])
        check(f"{prefix} usage requested from upstream when client didn't", seen["chat"].get("stream_options") == {"include_usage": True}, seen["chat"].get("stream_options"))
        stream(p, "up", "hi", stream_options={"include_usage": False})
        check(f"{prefix} client's explicit include_usage:false is respected", seen["chat"]["stream_options"] == {"include_usage": False}, seen["chat"].get("stream_options"))
        st, text = stream(p, "down", "hi")
        check(f"{prefix} unreachable model server -> 503 with message", st == 503 and "message" in json.loads(text).get("error", {}), (st, text))
        st, text = stream(p, "up", "reject")
        err = json.loads(text).get("error", {}) if st != 200 else {}
        check(f"{prefix} fast upstream rejection keeps status 400 + message", st == 400 and err.get("message") == "prompt too long", (st, text))
        st, text = stream(p, "up", "slow-reject")
        chunks, _, done = sse(text)
        errchunk = next((k for k in chunks if "error" in k), {})
        check(f"{prefix} rejection after the early 200: error chunk with finish_reason=error then [DONE]",
              st == 200 and done and errchunk.get("error", {}).get("message") == "prompt too long"
              and errchunk["choices"][0]["finish_reason"] == "error", (st, text[:200]))

    print("\n=== /openai/v1/models architecture.input_modalities")
    registry._registry["vis"] = SubserverConfig(name="vis", url=f"http://127.0.0.1:{PORT}", vision=True, vision_known=True)
    registry._registry["txt"] = SubserverConfig(name="txt", url=f"http://127.0.0.1:{PORT}", vision=False, vision_known=True)
    registry._registry["unk"] = SubserverConfig(name="unk", url=f"http://127.0.0.1:{PORT}")
    entries = {m["id"]: m for m in c.get("/openai/v1/models").json()["data"]}
    check("vision model -> input_modalities [text, image]", entries["vis"].get("architecture", {}).get("input_modalities") == ["text", "image"], entries["vis"].get("architecture"))
    check("text-only model -> input_modalities [text]", entries["txt"].get("architecture", {}).get("input_modalities") == ["text"], entries["txt"].get("architecture"))
    check("unknown vision status -> `architecture` omitted (not guessed)", "architecture" not in entries["unk"], entries["unk"].get("architecture"))
    for k in ("vis", "txt", "unk"):
        del registry._registry[k]

    print("\n=== reasoning replay reaches the upstream")
    msgs = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a", "reasoning": "why", "reasoning_details": [{"type": "reasoning.text", "text": "why"}]},
            {"role": "user", "content": "hi"}]
    c.post("/openrouter/v1/chat/completions", json={"model": "up", "messages": msgs})
    sent = seen["chat"]
    check("openrouter: assistant `reasoning` -> reasoning_content, aliases removed",
          sent["messages"][1].get("reasoning_content") == "why" and "reasoning" not in sent["messages"][1]
          and "reasoning_details" not in sent["messages"][1], sent["messages"][1])
    check("openrouter: preserve_reasoning=true set", sent.get("chat_template_kwargs") == {"preserve_reasoning": True}, sent.get("chat_template_kwargs"))
    c.post("/openai/v1/chat/completions", json={"model": "up", "messages": msgs, "reasoning": {"context": "current_turn"}})
    check("openai: reasoning.context current_turn -> preserve_reasoning=false", seen["chat"].get("chat_template_kwargs") == {"preserve_reasoning": False}, seen["chat"].get("chat_template_kwargs"))
    check("openai: `reasoning` object not forwarded to llama-server", "reasoning" not in seen["chat"], list(seen["chat"]))

    print("\n=== ollama")
    r = c.post("/ollama/api/chat", json={"model": "up", "stream": False, "messages": [{"role": "user", "content": "hi"}]})
    d = r.json()
    check("ollama chat non-stream: durations + counts + done_reason",
          r.status_code == 200 and d.get("done_reason") == "stop" and d.get("prompt_eval_count") == 3 and d.get("eval_count") == 2
          and d.get("prompt_eval_duration") == 5_000_000 and d.get("eval_duration") == 7_000_000
          and d.get("total_duration", 0) >= 12_000_000 and d.get("load_duration") == 0, d)
    with c.stream("POST", "/ollama/api/chat", json={"model": "up", "messages": [{"role": "user", "content": "hi"}]}) as r:
        lines = [json.loads(x) for x in r.read().decode().split("\n") if x.strip()]
    fin = lines[-1]
    check("ollama chat stream: final line has counts + durations from timings",
          fin.get("done") and fin.get("prompt_eval_count") == 3 and fin.get("eval_count") == 2
          and fin.get("prompt_eval_duration") == 5_000_000 and "total_duration" in fin, fin)
    r = c.post("/ollama/api/chat", json={"model": "down", "messages": [{"role": "user", "content": "hi"}]})
    check("ollama chat: unreachable model server -> 503 {error}", r.status_code == 503 and "error" in r.json(), (r.status_code, r.text))
    r = c.post("/ollama/api/chat", json={"model": "up", "stream": False, "messages": [{"role": "user", "content": "reject"}]})
    check("ollama chat: upstream 400 keeps status + message", r.status_code == 400 and r.json().get("error") == "prompt too long", (r.status_code, r.text))
    r = c.post("/ollama/api/chat", json={"model": "up", "messages": [{"role": "user", "content": "reject"}]})
    check("ollama chat stream: upstream 400 keeps status (not a 200 with an error line)", r.status_code == 400, (r.status_code, r.text))
    r = c.post("/ollama/api/generate", json={"model": "up", "prompt": "1+1=", "stream": False})
    d = r.json()
    check("ollama generate non-stream: done_reason + counts + durations",
          d.get("done_reason") == "length" and d.get("prompt_eval_count") == 2 and d.get("eval_count") == 1 and "total_duration" in d, d)
    r = c.post("/ollama/api/generate", json={"model": "down", "prompt": "x"})
    check("ollama generate: unreachable model server -> 503", r.status_code == 503, r.status_code)

    print(f"\n{len(FAILS)} failure(s)")
    for f in FAILS:
        print("  -", f)
    return len(FAILS)


if __name__ == "__main__":
    sys.exit(min(main(), 125))
