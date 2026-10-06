# metallama/app/gateway

Client-facing gateways in front of the llama.cpp servers: Ollama (`/ollama`), OpenAI
(`/openai/v1`, alias `/ollama/v1`), OpenRouter (`/openrouter/v1`) and native llama.cpp in router-mode shape (`/llamacpp`).
Shared registry, lazy probing, streaming proxy and reasoning normalization live alongside.

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Empty package marker |
| `config.py` | Loads unified `config.yaml` → `AppConfig` with `SubserverConfig` list (merges managed + remote) |
| `schemas.py` | Pydantic models for Ollama and OpenAI request/response schemas |
| `registry.py` | In-memory registry of subservers by name; `init_registry()`, `get_subserver()` |
| `probe.py` | Async probing of upstream servers: fetches `/props` and `/v1/models` to backfill metadata |
| `config.yaml` | Legacy YAML config listing subservers — now loaded from unified `config.yaml` |
| `proxy.py` | Streams an upstream response back verbatim (status + content type preserved) |
| `reasoning.py` | Resolved effort → `chat_template_kwargs` (`reasoning_effort` / `enable_thinking=false`) |
| `replay.py` | History reasoning → `reasoning_content`; `preserve_reasoning` (chat + Responses) |
| `openrouter.py` | OpenRouter-flavoured routes, mounted at `/openrouter` (built on `openai.py`) |
| `ollama.py` | Ollama API routes, mounted at `/ollama` |
| `openai.py` | OpenAI-compatible routes, mounted at `/openai` (and `/ollama` as a hidden alias) |
| `llamacpp.py` | Native llama.cpp API at `/llamacpp`, router-mode shape (routes by `model`) |

## Key Classes & Functions

| Name | File | What it does |
|------|------|-------------|
| `SubserverConfig` | schemas.py | Pydantic model: name, url, size, family, parameter_size, context_length, upstream metadata |
| `AppConfig` | schemas.py | Container for list of `SubserverConfig` |
| `OllamaChatRequest` | schemas.py | Ollama chat request schema (model, messages, stream, options) |
| `OllamaGenerateRequest` | schemas.py | Ollama generate request schema (model, prompt, stream, options) |
| `OllamaShowRequest` | schemas.py | Ollama show request with model/name validation |
| `OpenAIChatRequest` | schemas.py | OpenAI chat completion request (extra fields allowed) |
| `OpenAICompletionRequest` | schemas.py | OpenAI completion request |
| `load_config()` | config.py | Merges managed_servers + remote_servers from unified config into `AppConfig` |
| `init_registry()` | registry.py | Populates global `_registry` dict from `AppConfig` |
| `get_subserver()` | registry.py | Looks up subserver by model name or upstream_model_id (404 if missing) |
| `get_all_subservers()` | registry.py | Returns all registered subservers |
| `probe_one()` | probe.py | Probes a single upstream server: context, params, quantization, vision / thinking / tools capabilities |
| `list_tags()` | ollama.py | `GET /api/tags` — lists healthy models plus configured virtual effort variants |
| `list_running()` | ollama.py | `GET /api/ps` — lists running (healthy) models |
| `version()` | ollama.py | `GET /api/version` — returns gateway version |
| `show()` | ollama.py | `POST /api/show` — model info/details, including vision capability |
| `chat()` | ollama.py | `POST /api/chat` — translates Ollama chat → OpenAI, streams NDJSON |
| `generate_endpoint()` | ollama.py | `POST /api/generate` — translates Ollama generate → OpenAI completions |
| `pull()` / `push()` / `copy()` / `delete()` | ollama.py | Stubbed management endpoints (return "not supported") |
| `_run_chat()` | ollama.py | Sends a chat payload upstream and answers in Ollama chat or generate shape |
| `_stream_chat()` | ollama.py | Translates OpenAI SSE stream → Ollama NDJSON (thinking, accumulated tool calls, final stats) |
| `_run_raw_generate()` | ollama.py | `raw: true` generate via `/v1/completions` |
| `embed()` / `embeddings_legacy()` | ollama.py | `POST /api/embed` and `/api/embeddings` via upstream `/v1/embeddings` |
| `_ollama_message_to_openai()` | ollama.py | Converts an Ollama chat message to OpenAI shape (tool calls + base64 images → multimodal content parts) |
| `_openai_tool_calls_to_ollama()` | ollama.py | Converts OpenAI tool_calls back to Ollama shape |
| `root()` | ollama.py | `GET /ollama` — "Ollama is running" health ping |
| `apply_reasoning()` | reasoning.py | Replay (`replay.apply_replay`), then the resolved effort into `chat_template_kwargs` |
| `proxy()` | proxy.py | Streams an upstream response back verbatim (status + content type preserved) |
| `passthrough()` | llamacpp.py | `/{path}` — picks the server from body `model` / `?model=` and forwards |
| `list_models()` / `load_model()` / `unload_model()` | llamacpp.py | Router-mode `/models`, `/models/load`, `/models/unload` |
| `list_models()` | openai.py | `GET /v1/models` — lists healthy models plus configured virtual variants |
| `chat_completions()` | openai.py | `POST /v1/chat/completions` — passthrough (streaming or JSON) |
| `completions()` | openai.py | `POST /v1/completions` — passthrough |
| `embeddings()` | openai.py | `POST /v1/embeddings` — passthrough |

## See Also
- [Architecture overview](../notes/architecture.md)
- [API reference](../notes/api.md)
