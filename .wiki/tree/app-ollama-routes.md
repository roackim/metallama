# metallama/app/ollama/routes

HTTP routes for the Ollama-compatible and OpenAI-compatible gateway endpoints. Both
routers are mounted at `/ollama` in `main.py`.

## Files

| File | Purpose |
|------|---------|
| `ollama.py` | Ollama API routes (`/api/tags`, `/api/chat`, `/api/generate`, etc.) |
| `openrouter.py` | OpenRouter-flavoured routes (`/v1/models`, `/v1/chat/completions`), mounted at `/openrouter` |
| `openai.py` | OpenAI-compatible passthrough routes (`/v1/models`, `/v1/chat/completions`, `/v1/responses`, …), mounted at `/openai` and `/ollama` |
| `__init__.py` | Empty package marker |

## Key Classes & Functions

| Name | File | What it does |
|------|------|-------------|
| `list_tags()` | ollama.py | `GET /api/tags` — lists healthy models (base + virtual `name:effort` variants), with `thinking` capability and `reasoning_efforts` |
| `list_running()` | ollama.py | `GET /api/ps` — lists running (healthy) models |
| `version()` | ollama.py | `GET /api/version` — returns gateway version |
| `show()` | ollama.py | `POST /api/show` — model info/details, including vision/thinking capabilities and allowed `reasoning_efforts` |
| `chat()` | ollama.py | `POST /api/chat` — translates Ollama chat → OpenAI (incl. `think`), streams NDJSON with reasoning as `message.thinking` |
| `generate_endpoint()` | ollama.py | `POST /api/generate` — translates Ollama generate → OpenAI completions |
| `pull()` / `push()` / `copy()` / `delete()` | ollama.py | Stubbed management endpoints (return "not supported") |
| `_stream_chat()` | ollama.py | Translates OpenAI SSE stream → Ollama NDJSON (accumulates tool-call fragments) |
| `_stream_generate()` | ollama.py | Translates OpenAI SSE stream → Ollama generate NDJSON |
| `_ollama_message_to_openai()` | ollama.py | Converts an Ollama chat message to OpenAI shape (tool calls + base64 images → multimodal content parts) |
| `_openai_tool_calls_to_ollama()` | ollama.py | Converts OpenAI tool_calls back to Ollama shape |
| `_capabilities()` | ollama.py | Ollama capability list (`vision`, `thinking` when the template supports efforts) |
| `_apply_reasoning_effort()` | ollama.py | Resolves the request's effort (`registry.resolve_reasoning_effort`) and sets top-level `reasoning_effort` on the upstream payload; no token budget is sent |
| `list_models()` | openai.py | `GET /v1/models` — lists healthy models plus configured virtual variants |
| `open_upstream()` | openai.py | Shared request half: parses body, resolves server, strips suffix, runs an optional dialect `prepare`, validates/applies effort, opens the upstream response |
| `relay()` | openai.py | Relays an upstream response unchanged (raw SSE or buffered, status preserved) |
| `_forward()` | openai.py | `open_upstream` + `relay`; gateway errors in OpenAI shape via `_openai_error()` |
| `healthy_subservers()` | openai.py | Servers answering `/health`, lazily probed; used by both `/models` listings |
| `_reasoning_fields()` | openai.py | OpenRouter-style `supported_parameters` + `reasoning` object for a `/models` entry |
| `_model_entry()` | openrouter.py | One `/models` entry in OpenRouter's shape |
| `_prepare()` / `_wants_reasoning()` | openrouter.py | Map OpenRouter request fields (`reasoning.enabled/exclude`, `include_reasoning`, routing fields) |
| `_translate_stream()` | openrouter.py | Re-serializes SSE, renaming `reasoning_content` → `reasoning` (or dropping it) |
| `chat_completions()` | openai.py | `POST /v1/chat/completions` — `_forward` with effort validation |
| `responses()` | openai.py | `POST /v1/responses` — `_forward` with effort validation (`reasoning.effort`) |
| `completions()` | openai.py | `POST /v1/completions` — `_forward` |
| `embeddings()` | openai.py | `POST /v1/embeddings` — `_forward` |

## See Also
- [Ollama gateway internals](../tree/app-ollama.md)
- [API surface](../notes/api.md)