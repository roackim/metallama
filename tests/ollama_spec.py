"""Ollama API spec checks (ollama docs/api.md) against a running metallama, live model.

    uv run python tests/ollama_spec.py http://127.0.0.1:8010 [MODEL]
"""
import base64, json, struct, sys, zlib
import httpx

BASE = sys.argv[1].rstrip("/") + "/ollama"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "Qwen-27B-Q8_0"
c = httpx.Client(timeout=300)
results = []


def check(name, ok, info=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {info}" if info and not ok else ""))


def nd(r):
    return [json.loads(l) for l in r.text.splitlines() if l.strip()]


def safe(name, fn):
    try:
        fn()
    except Exception as e:  # a crash is a failure, keep going
        check(name, False, f"{type(e).__name__}: {str(e)[:150]}")


def blue_png():
    raw = b"".join(b"\x00" + b"\x00\x00\xff" * 32 for _ in range(32))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode()


OK = [{"role": "user", "content": "Reply with exactly: OK"}]
FINAL = ("done_reason", "total_duration", "load_duration", "prompt_eval_count",
         "prompt_eval_duration", "eval_count", "eval_duration")


def t_root():
    r = c.get(BASE)
    check("GET / → 200 'Ollama is running'", r.status_code == 200 and "Ollama is running" in r.text, f"{r.status_code} {r.text[:80]}")


def t_version():
    r = c.get(f"{BASE}/api/version")
    check("/api/version → {version}", r.status_code == 200 and "version" in r.json(), r.text[:80])


def t_tags():
    m = c.get(f"{BASE}/api/tags").json()["models"]
    e = next(x for x in m if x["model"].startswith(MODEL))
    d = e.get("details", {})
    need = {"name", "model", "modified_at", "size", "digest", "details"}
    check("/api/tags entry fields", need <= e.keys(), sorted(need - e.keys()))
    dneed = {"format", "family", "families", "parameter_size", "quantization_level"}
    check("/api/tags details fields", dneed <= d.keys(), sorted(dneed - d.keys()))
    check("/api/tags no guessed family ('llama' on a Qwen model)", d.get("family") != "llama", d.get("family"))
    check("/api/tags real quantization (Q8_0)", d.get("quantization_level") == "Q8_0", d.get("quantization_level"))


def t_ps():
    m = c.get(f"{BASE}/api/ps").json()["models"]
    e = next(x for x in m if x["model"].startswith(MODEL))
    check("/api/ps has expires_at + size_vram", {"expires_at", "size_vram"} <= e.keys(), sorted(e.keys()))


def t_show():
    r = c.post(f"{BASE}/api/show", json={"model": MODEL})
    j = r.json()
    check("/api/show 200 with details/model_info/capabilities/parameters",
          r.status_code == 200 and {"details", "model_info", "capabilities", "parameters"} <= j.keys(), r.text[:150])
    caps = j.get("capabilities", [])
    check("/api/show capabilities include thinking (Qwen 3.x)", "thinking" in caps, caps)
    check("/api/show capabilities include vision", "vision" in caps, caps)
    check("/api/show no hardcoded stop token guess", "<|im_end|>" not in j.get("parameters", ""), j.get("parameters"))
    mi = j.get("model_info", {})
    arch = mi.get("general.architecture")
    check("/api/show model_info[<arch>.context_length] resolvable", f"{arch}.context_length" in mi, list(mi)[:6])
    check("/api/show general.parameter_count is a number", isinstance(mi.get("general.parameter_count"), int), mi.get("general.parameter_count"))


def t_chat_stream():
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "messages": OK})
    lines = nd(r)
    check("chat stream content-type application/x-ndjson", "ndjson" in r.headers.get("content-type", ""), r.headers.get("content-type"))
    think = "".join(l.get("message", {}).get("thinking", "") for l in lines)
    content = "".join(l.get("message", {}).get("content", "") for l in lines)
    check("chat stream: thinking in message.thinking", len(think) > 0, f"thinking={len(think)}")
    check("chat stream: no non-standard message.reasoning", not any("reasoning" in l.get("message", {}) for l in lines))
    check("chat stream: content 'OK'", content.strip() == "OK", repr(content[:60]))
    last = lines[-1]
    check("chat stream: final has done + all stats", last.get("done") and all(k in last for k in FINAL), sorted(set(FINAL) - last.keys()))
    check("chat stream: eval_count > 0", last.get("eval_count", 0) > 0, last.get("eval_count"))
    return len(think)


def t_chat_nonstream():
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "messages": OK, "stream": False})
    j = r.json()
    check("chat non-stream: single object, message.thinking", r.status_code == 200 and bool(j.get("message", {}).get("thinking")), r.text[:150])
    check("chat non-stream: all final stats", all(k in j for k in FINAL), sorted(set(FINAL) - j.keys()))


def t_think_levels(default_len):
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "messages": OK, "stream": False, "think": False})
    j = r.json()
    check("think=false → no thinking", r.status_code == 200 and not j.get("message", {}).get("thinking"), r.text[:150])
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "messages": OK, "stream": False, "think": "low"})
    j = r.json()
    low = len(j.get("message", {}).get("thinking", "") or "")
    check("think='low' → 200 with thinking", r.status_code == 200 and low > 0, r.text[:150])
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "messages": OK, "stream": False, "think": "high"})
    check("think='high' → 200", r.status_code == 200, r.text[:200])
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "messages": OK, "stream": False, "think": "max"})
    check("think='max' (spec level) → not a 5xx / template crash", r.status_code < 500, f"{r.status_code} {r.text[:200]}")
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "messages": OK, "stream": False, "think": True})
    check("think=true → 200 with thinking", r.status_code == 200 and bool(r.json().get("message", {}).get("thinking")), r.text[:150])


def t_format():
    schema = {"type": "object", "properties": {"name": {"type": "string"}, "age": {"type": "integer"}}, "required": ["name", "age"]}
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "stream": False, "think": False, "format": schema,
                                          "messages": [{"role": "user", "content": "Bob is 3 years old. Describe him."}]})
    content = r.json().get("message", {}).get("content", "")
    try:
        obj = json.loads(content); ok = set(obj) == {"name", "age"}
    except ValueError:
        ok = False
    check("format=<JSON schema> → content is raw JSON matching schema", ok, repr(content[:80]))
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "stream": False, "think": False, "format": "json",
                                          "messages": [{"role": "user", "content": "Give name=Bob age=3 as JSON"}]})
    content = r.json().get("message", {}).get("content", "")
    try:
        json.loads(content); ok = True
    except ValueError:
        ok = False
    check("format='json' → content parses as JSON", ok, repr(content[:80]))


TOOLS = [{"type": "function", "function": {"name": "get_weather", "description": "Get weather for a city",
          "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]


def t_tools():
    msgs = [{"role": "user", "content": "What's the weather in Paris? Use the tool."}]
    lines = nd(c.post(f"{BASE}/api/chat", json={"model": MODEL, "messages": msgs, "tools": TOOLS, "think": False}))
    calls = [tc for l in lines for tc in l.get("message", {}).get("tool_calls", []) or []]
    ok = bool(calls) and calls[0]["function"]["name"] == "get_weather" and isinstance(calls[0]["function"]["arguments"], dict)
    check("tools stream: tool_calls with dict arguments", ok, json.dumps(lines[-2:])[:200])
    if not ok:
        return
    follow = msgs + [{"role": "assistant", "content": "", "tool_calls": calls},
                     {"role": "tool", "tool_name": "get_weather", "content": "18°C, sunny"}]
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "messages": follow, "tools": TOOLS, "think": False, "stream": False})
    content = r.json().get("message", {}).get("content", "")
    check("tools round-trip: tool result (tool_name) used in answer", r.status_code == 200 and "18" in content, f"{r.status_code} {content[:100] or r.text[:150]}")


def t_images():
    img = blue_png()
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "stream": False, "think": False, "messages": [
        {"role": "user", "content": "What color is this image? One word.", "images": [img]}]})
    content = r.json().get("message", {}).get("content", "")
    check("chat images: model sees the image (blue)", "blue" in content.lower(), f"{r.status_code} {content[:80] or r.text[:150]}")
    r = c.post(f"{BASE}/api/generate", json={"model": MODEL, "stream": False, "think": False,
                                              "prompt": "What color is this image? One word.", "images": [img]})
    resp = r.json().get("response", "")
    check("generate images: model sees the image (blue)", "blue" in resp.lower(), f"{r.status_code} {resp[:80] or r.text[:150]}")


def t_generate():
    r = c.post(f"{BASE}/api/generate", json={"model": MODEL, "prompt": "Reply with exactly: OK", "stream": False, "think": False})
    j = r.json()
    check("generate: templated prompt → response 'OK'", j.get("response", "").strip() == "OK", repr(j.get("response", "")[:60]))
    check("generate: all final stats", all(k in j for k in FINAL), sorted(set(FINAL) - j.keys()))
    lines = nd(c.post(f"{BASE}/api/generate", json={"model": MODEL, "prompt": "Reply with exactly: OK"}))
    think = "".join(l.get("thinking", "") for l in lines)
    resp = "".join(l.get("response", "") for l in lines)
    check("generate stream: thinking in `thinking`, not in `response`", len(think) > 0 and "<think>" not in resp and resp.strip() == "OK",
          f"thinking={len(think)} response={resp[:60]!r}")
    r = c.post(f"{BASE}/api/generate", json={"model": MODEL, "stream": False, "think": False,
                                              "system": "You are a pirate named Zork. Always state your name.", "prompt": "Who are you?"})
    check("generate: `system` honoured", "zork" in r.json().get("response", "").lower(), r.json().get("response", "")[:80])
    r = c.post(f"{BASE}/api/generate", json={"model": MODEL, "prompt": "1, 2, 3, 4,", "raw": True, "stream": False,
                                              "options": {"num_predict": 6, "temperature": 0}})
    check("generate raw=true: plain continuation", "5" in r.json().get("response", ""), r.text[:150])


def t_load():
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "messages": []})
    j = nd(r)[-1] if r.status_code == 200 else {}
    check("chat empty messages → done_reason 'load'", r.status_code == 200 and j.get("done_reason") == "load", f"{r.status_code} {r.text[:150]}")
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "messages": [], "keep_alive": 0})
    j = nd(r)[-1] if r.status_code == 200 else {}
    check("chat empty + keep_alive 0 → done_reason 'unload'", r.status_code == 200 and j.get("done_reason") == "unload", f"{r.status_code} {r.text[:150]}")
    r = c.post(f"{BASE}/api/generate", json={"model": MODEL})
    j = nd(r)[-1] if r.status_code == 200 else {}
    check("generate without prompt → done_reason 'load'", r.status_code == 200 and j.get("done_reason") == "load", f"{r.status_code} {r.text[:150]}")


def t_options():
    r = c.post(f"{BASE}/api/chat", json={"model": MODEL, "stream": False, "think": False,
                                          "messages": [{"role": "user", "content": "Count from 1 to 50 separated by commas."}],
                                          "options": {"num_predict": 5, "top_k": 1, "repeat_penalty": 1.0}})
    j = r.json()
    check("options.num_predict caps eval_count", r.status_code == 200 and j.get("eval_count", 99) <= 5 and j.get("done_reason") == "length",
          f"eval_count={j.get('eval_count')} done_reason={j.get('done_reason')}")


def t_embed_errors():
    r = c.post(f"{BASE}/api/embed", json={"model": MODEL, "input": "hi"})
    check("/api/embed exists (not 404/405; server lacks --embeddings → error body)", r.status_code not in (404, 405) and "error" in r.json(), f"{r.status_code} {r.text[:120]}")
    r = c.post(f"{BASE}/api/chat", json={"model": "no-such-model", "messages": OK})
    j = r.json()
    check("unknown model → 404 {\"error\": str}", r.status_code == 404 and isinstance(j.get("error"), str), f"{r.status_code} {r.text[:120]}")


for name, fn in [("root", t_root), ("version", t_version), ("tags", t_tags), ("ps", t_ps), ("show", t_show)]:
    safe(name, fn)
default_len = 0
try:
    default_len = t_chat_stream()
except Exception as e:
    check("chat stream", False, str(e)[:150])
for name, fn in [("chat non-stream", t_chat_nonstream), ("think", lambda: t_think_levels(default_len)), ("format", t_format),
                 ("tools", t_tools), ("images", t_images), ("generate", t_generate), ("load", t_load),
                 ("options", t_options), ("embed/errors", t_embed_errors)]:
    safe(name, fn)
print(f"\n{results.count(True)}/{len(results)} passed")
