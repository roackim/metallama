# API Reference

## Management API

Model lifecycle, configuration, and service endpoints.

### Models

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/models` | GET | — | List all servers (managed + remote) with status |
| `/api/models/{id}/status` | GET | — | Get status for a single server |
| `/api/models/{id}/start` | POST | admin | Start a managed server |
| `/api/models/{id}/stop` | POST | admin | Stop a managed server |
| `/api/models/{id}/command` | GET | — | Preview the command that would be executed |
| `/api/models/{id}/config` | POST | admin | Update managed server config |
| `/api/models/create` | POST | admin | Add a managed or remote server |
| `/api/models/{id}` | DELETE | admin | Delete a server |

### Servers (aliases)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/servers` | GET | — | List all servers (alias for `/api/models`) |
| `/api/servers/{id}/status` | GET | — | Server status |
| `/api/servers/{id}/start` | POST | admin | Start server |
| `/api/servers/{id}/stop` | POST | admin | Stop server |
| `/api/llm/servers` | GET | — | List LLM servers |
| `/api/llm/servers/status` | GET | — | List LLM server statuses |
| `/api/llm/servers/{id}/status` | GET | — | LLM server status |
| `/api/llm/servers/{id}/start` | POST | admin | Start LLM server |
| `/api/llm/servers/{id}/stop` | POST | admin | Stop LLM server |

### Remote Servers

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/remote-servers/{name}/config` | POST | admin | Update remote server config |

### Config & Health

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/config` | GET | — | Get runtime config (binary paths, URLs) |
| `/api/health` | GET | — | Binary availability & auth status |

### System

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/system/vram` | GET | — | Current VRAM usage (nvidia-smi) |
| `/api/system/vram/history` | GET | — | VRAM history samples |
| `/api/system/ram` | GET | — | Current RAM usage (psutil) |
| `/api/system/ram/history` | GET | — | RAM history samples |
| `/api/model-files` | GET | — | List `.gguf` files in `METALLAMA_MODELS_DIR` |

### Auth

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/auth/status` | GET | — | Whether auth is enabled |
| `/api/auth/login` | POST | — | Login, returns session token |
| `/api/auth/logout` | POST | — | Revoke session |
| `/api/auth/verify` | GET | — | Validate current Bearer token |

### HuggingFace

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/hf/search?q=…` | GET | — | Search HF Hub for models |
| `/api/hf/models/{ns}/{repo}/files` | GET | — | List `.gguf` files in a repo |
| `/api/hf/download` | POST | admin | Download files (streaming NDJSON) |

## Ollama API (mounted at `/ollama`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ollama/api/tags` | GET | List available models (Ollama format) |
| `/ollama/api/ps` | GET | List running models |
| `/ollama/api/version` | GET | Version info |
| `/ollama/api/show` | POST | Model details |
| `/ollama/api/chat` | POST | Chat completion (streaming NDJSON) |
| `/ollama/api/generate` | POST | Text generation (streaming NDJSON) |

## OpenAI API (mounted at `/openai`)

Recommended API for clients: `base_url = http://<host>:8010/openai/v1`. A thin router
over llama-server's native OpenAI API — resolves the upstream from `model`, strips the
virtual `:effort` suffix, validates the reasoning effort, and relays body and response
unchanged (SSE streamed byte for byte; upstream error status/body preserved). Gateway
errors (unknown model, disallowed effort, non-JSON body) use OpenAI's
`{"error": {"message", "type", "code"}}` shape. The same routes are also mounted at
`/ollama/v1/...` for legacy clients.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/openai/v1/models` | GET | List models (base + `:effort` variants; `meta.reasoning_efforts`) |
| `/openai/v1/chat/completions` | POST | Chat completion passthrough (`reasoning_effort`) |
| `/openai/v1/responses` | POST | Responses API passthrough (`reasoning.effort`) |
| `/openai/v1/completions` | POST | Completion passthrough |
| `/openai/v1/embeddings` | POST | Embeddings passthrough |

Each `/v1/models` entry with allowed efforts also carries OpenRouter's reasoning
advertisement: `supported_parameters: ["include_reasoning", "reasoning",
"reasoning_effort"]` and `reasoning: {mandatory, default_enabled, supported_efforts,
default_effort?}`. `supported_efforts` is the allowed set in canonical order
(`none` only when allowed); `mandatory` is true when `none` isn't allowed;
`default_effort` is the template's `reasoning_effort|default('x')`, emitted only when
it is itself allowed (so a client can send it back without a 400). No null values —
clients (moka) store entries as TOML.

## OpenRouter-flavoured API (mounted at `/openrouter`)

`base_url = http://<host>:8010/openrouter/v1`, for clients with an OpenRouter provider
type. Same routing/effort validation as `/openai` (shared `open_upstream()`), plus:

- `/v1/models` in OpenRouter's shape: `architecture` (modality, input/output
  modalities, tokenizer `Other`), zero `pricing`, `top_provider`, full
  `supported_parameters`, `reasoning` object. Base + virtual ids per the toggle.
- Request: `reasoning.effort` → effort; `reasoning.enabled: false` → `none`;
  `reasoning.exclude: true` or `include_reasoning: false` → reasoning stripped from
  the response; `reasoning.max_tokens` ignored (no budgets); OpenRouter-only fields
  (`provider`, `models`, `route`, `transforms`, `plugins`, `usage`, `user`) dropped.
- Response: llama.cpp `reasoning_content` renamed to `reasoning` in `message` and in
  streamed `delta`s (SSE re-serialized line by line).

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/openrouter/v1/models` | GET | Models in OpenRouter format |
| `/openrouter/v1/chat/completions` | POST | Chat completion (OpenRouter reasoning conventions) |

## See Also
- [Architecture overview](./architecture.md)
- [Main routes](../tree/app.md)
- [Ollama routes](../tree/app-ollama-routes.md)

## Reasoning efforts

The effort is chosen **per request**; a server's `reasoning_efforts` list in
`config.yaml` only restricts which levels are allowed (∩ what the chat template
supports, probed from `/props`). Sources, highest priority first:

| Source | API |
|---|---|
| `think: false` → `none`; `think: "low"` etc. → that level (`true` = thinking on, no level) | Ollama |
| `reasoning_effort` (top level, or in Ollama `options`) | OpenAI / Ollama |
| `reasoning.effort` | OpenAI Responses / OpenRouter style |
| model suffix `name:low` (virtual model) | any — only when the server has `virtualize_efforts: true` |

- The gateway forwards the level as top-level `reasoning_effort`; llama-server passes
  it to the template and maps `none` to `enable_thinking=false`. No token budget is
  sent (budgets hard-cut reasoning).
- A level outside the allowed set → `400 {"error", "allowed_efforts"}`. Servers with
  no allowed efforts configured are not policed.
- Listings advertise the allowed set (`reasoning_efforts` in `/api/tags`, `/api/show`,
  `/v1/models` meta) and the Ollama `thinking` capability. The base model is always
  listed; `name:effort` variants only when the server virtualizes efforts
  (`virtualize_efforts`, per managed server in `config.yaml`). Otherwise a suffixed
  name is 404 "model not found".
- Ollama responses carry reasoning in `message.thinking` (Ollama's native field).

