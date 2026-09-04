# metallama/app/ollama/routes

HTTP routes for the Ollama-compatible and OpenAI-compatible gateway endpoints. Both
routers are mounted at `/ollama` in `main.py`.

## Files

| File | Purpose |
|------|---------|
| `ollama.py` | Ollama API routes (`/api/tags`, `/api/chat`, `/api/generate`, etc.) |
| `openai.py` | OpenAI-compatible passthrough routes (`/v1/models`, `/v1/chat/completions`, etc.) |
| `__init__.py` | Empty package marker |

## Key Classes & Functions

| Name | File | What it does |
|------|------|-------------|
| `list_tags()` | ollama.py | `GET /api/tags` — lists healthy models with details |
| `list_running()` | ollama.py | `GET /api/ps` — lists running (healthy) models |
| `version()` | ollama.py | `GET /api/version` — returns gateway version |
| `show()` | ollama.py | `POST /api/show` — model info/details |
| `chat()` | ollama.py | `POST /api/chat` — translates Ollama chat → OpenAI, streams NDJSON |
| `generate_endpoint()` | ollama.py | `POST /api/generate` — translates Ollama generate → OpenAI completions |
| `pull()` / `push()` / `copy()` / `delete()` | ollama.py | Stubbed management endpoints (return "not supported") |
| `_stream_chat()` | ollama.py | Translates OpenAI SSE stream → Ollama NDJSON (accumulates tool-call fragments) |
| `_stream_generate()` | ollama.py | Translates OpenAI SSE stream → Ollama generate NDJSON |
| `_ollama_message_to_openai()` | ollama.py | Converts an Ollama chat message to OpenAI shape (tool calls + base64 images → multimodal content parts) |
| `_openai_tool_calls_to_ollama()` | ollama.py | Converts OpenAI tool_calls back to Ollama shape |
| `_extract_reasoning_effort()` | ollama.py | Pulls `reasoning_effort` from top-level body or `options` |
| `_apply_reasoning_effort()` | ollama.py | Maps reasoning_effort → llama-server `reasoning_effort` + `reasoning_budget` + `chat_template_kwargs` |
| `list_models()` | openai.py | `GET /v1/models` — lists healthy models (meta includes `vision`) |
| `chat_completions()` | openai.py | `POST /v1/chat/completions` — passthrough (streaming or JSON) |
| `completions()` | openai.py | `POST /v1/completions` — passthrough |
| `embeddings()` | openai.py | `POST /v1/embeddings` — passthrough |

## See Also
- [Ollama gateway internals](../tree/app-ollama.md)
- [API surface](../notes/api.md)