# Gateways

Metallama sits in front of every llama.cpp server it knows (managed and remote)
and exposes them through three client-facing APIs:

| Gateway | Base URL | Use it for |
|---|---|---|
| **Ollama** | `/ollama` | Ollama clients: VS Code / Copilot, Open WebUI, `ollama` libraries |
| **OpenAI** | `/openai/v1` | OpenAI-compatible clients: Cline, Continue, agents, SDKs |
| **llama.cpp** | `/llamacpp` | Clients that speak llama-server's native API (router mode) |

`/ollama/v1` is kept as an alias of `/openai/v1` for older client configs.

Code lives in `metallama/app/gateway/` (`ollama.py`, `openai.py`, `llamacpp.py`,
plus shared `registry.py`, `probe.py`, `proxy.py`, `reasoning.py`).

---

## Feature matrix

| Feature | Ollama `/ollama` | OpenAI `/openai/v1` | llama.cpp `/llamacpp` |
|---|---|---|---|
| **Model discovery** | ✅ `/api/tags` (running models) | ✅ `/v1/models` (running models) | ✅ `/models`, `/v1/models` (all models + load status) |
| **Effort variants listed** (`name:low`…) | ✅ | ✅ | ✅ |
| **Model details** | ✅ `/api/show`: context, params, quant, capabilities | ⚠️ `meta` in model list | ✅ `meta` in model list, `/props?model=` |
| **Running models** | ✅ `/api/ps` | ❌ | ✅ `status` in model list |
| **Reasoning effort** | ✅ `think`, `reasoning_effort`, `options.reasoning_effort`, `:suffix` | ✅ `reasoning_effort`, `reasoning.effort`, `:suffix` | ✅ same as OpenAI (chat) |
| **Disable thinking** | ✅ `think: false`, `none` | ✅ `none` | ✅ `none` |
| **Preserve thinking (history)** | ✅ `message.thinking` | ✅ `reasoning_content`, `reasoning`, `thinking`, `reasoning_details` | ✅ same as OpenAI (chat) |
| **`preserve_thinking` flag** | ✅ top-level or `options` | ✅ | ✅ (chat) |
| **Thinking in responses** | `message.thinking` / `thinking` | `reasoning_content` | `reasoning_content` |
| **Streaming** | ✅ NDJSON | ✅ SSE | ✅ SSE |
| **Tool calling** | ✅ (calls emitted whole) | ✅ (incremental) | ✅ (incremental) |
| **Vision** | ✅ `images` (chat + generate) | ✅ `image_url` parts | ✅ `image_url` parts / native |
| **Structured output** | ✅ `format`: `"json"` or JSON schema | ✅ `response_format` | ✅ `response_format`, `json_schema`, `grammar` |
| **Raw completion** (no chat template) | ✅ `/api/generate` + `raw: true` | ✅ `/v1/completions` | ✅ `/completion`, `/v1/completions` |
| **Embeddings** ¹ | ✅ `/api/embed`, `/api/embeddings` | ✅ `/v1/embeddings` | ✅ `/embedding`, `/v1/embeddings` |
| **Sampler options** | ⚠️ mapped subset (see below) | ✅ all llama-server fields | ✅ all |
| **Usage / timing stats** | ✅ `eval_count`, durations | ✅ `usage` + `timings` | ✅ `usage` + `timings` |
| **Load / unload models** | ⚠️ empty request is acknowledged, nothing started/stopped | ❌ | ✅ `/models/load`, `/models/unload` (admin, managed only) |
| **Native endpoints** (`tokenize`, `props`, `slots`, `infill`, `metrics`…) | ❌ | ❌ | ✅ |
| **Error shape** | `{"error": "..."}` | llama-server's errors ² | llama-server's `{"error": {code, message, type}}` |
| **Not supported** | `pull`, `push`, `copy`, `delete`, `create` | — | auto-loading a stopped model ³ |

1. Embeddings require the backing server to be started with `--embeddings`.
2. Unknown model on `/openai` returns an OpenAI-style `{"error": {...}}` (404).
3. Requests to a stopped model return `503` (`model server unreachable`); start it with `/models/load` or from the UI.

---

## Reasoning controls

Shared by all three gateways (`gateway/reasoning.py`). They apply to chat-style
requests: `/api/chat`, `/api/generate` (unless `raw`), and `chat/completions`.
Raw completions are forwarded untouched.

### Effort

Picked from the first source present:

1. Virtual model suffix: `Qwen3.6-35B:low`
2. `reasoning_effort` (top level)
3. `reasoning.effort` (OpenAI Responses / OpenRouter style)
4. `options.reasoning_effort`
5. `think` (Ollama: `true` / `false` / `"low"` / `"medium"` / `"high"`)

| Value | Sent upstream |
|---|---|
| `minimal`, `low` | `chat_template_kwargs.reasoning_effort = "low"`, budget 1024 |
| `medium` | `"medium"`, budget 4096 |
| `high`, `xhigh` | `"high"` / `"xhigh"`, unlimited |
| `none`, `false`, `off`, `0` | `chat_template_kwargs.enable_thinking = false` |
| anything else | passed through as-is |

llama-server ignores a top-level `reasoning_effort`; the chat template only reads
it from `chat_template_kwargs`, which is why the gateway rewrites it.

Virtual `:effort` models appear in model lists only for efforts that are both
enabled on the server (model settings in the UI) and supported by its chat
template (detected from `/props`).

### Preserved thinking

The chat template only renders past thinking from `message.reasoning_content`.
The gateway moves it there from whichever field the client used:

| Gateway | Accepted on assistant messages |
|---|---|
| Ollama | `thinking` |
| OpenAI / llama.cpp | `reasoning_content`, `reasoning`, `thinking`, `reasoning_details[].text` |

Set `preserve_thinking: false` to drop past thinking from the prompt (Qwen 3.x
templates keep it by default). It is forwarded as
`chat_template_kwargs.preserve_thinking`.

---

## Ollama — `/ollama`

| Method | Path | Notes |
|---|---|---|
| `GET` `HEAD` | `/ollama` | `Ollama is running` |
| `GET` | `/api/tags` | Running models (+ effort variants) |
| `GET` | `/api/ps` | Running models |
| `GET` | `/api/version` | Gateway version |
| `POST` | `/api/show` | Context, params, quant, capabilities (`tools`, `thinking`, `vision`) |
| `POST` | `/api/chat` | Chat; streams NDJSON |
| `POST` | `/api/generate` | Prompt through the chat template; `raw: true` skips it |
| `POST` | `/api/embed` | `input`: string or list |
| `POST` | `/api/embeddings` | Legacy single `prompt` |

- Empty `messages` / `prompt` is a load/unload ping, answered with
  `done_reason: "load"` (or `"unload"` when `keep_alive: 0`).
- Final `done` objects carry `prompt_eval_count`, `eval_count` and durations.
- Model details are only what llama-server reports (params, quantization);
  `family` is empty unless set on a remote server in `config.yaml`.
- Mapped `options`: `temperature`, `top_p`, `top_k`, `min_p`, `typical_p`,
  `seed`, `stop`, `num_predict`, `presence_penalty`, `frequency_penalty`,
  `repeat_penalty`, `repeat_last_n`, `mirostat`, `mirostat_tau`,
  `mirostat_eta`, `num_keep`. Others (e.g. `num_ctx`) are ignored; context is
  set on the server.

```bash
curl http://localhost:8010/ollama/api/chat -d '{
  "model": "Qwen3.6-35B-A3B-UD-Q4_K_XL-MTP",
  "messages": [{"role": "user", "content": "Hello"}],
  "think": "low"
}'
```

---

## OpenAI — `/openai/v1`

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/models` | Running models (+ effort variants) |
| `POST` | `/v1/chat/completions` | Reasoning controls applied, then passthrough |
| `POST` | `/v1/completions` | Passthrough |
| `POST` | `/v1/embeddings` | Passthrough |

Responses are streamed back verbatim: upstream status codes, error bodies and
content types are preserved. Any API key is accepted.

```bash
export OPENAI_BASE_URL="http://localhost:8010/openai/v1"
export OPENAI_API_KEY="metallama"

curl $OPENAI_BASE_URL/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "Qwen3.6-35B-A3B-UD-Q4_K_XL-MTP:low",
  "messages": [{"role": "user", "content": "Hello"}]
}'
```

---

## llama.cpp — `/llamacpp`

Behaves like a llama-server started in router mode (`--models-dir`): one base URL,
the model is chosen per request.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/models`, `/v1/models` | All models, `status.value`: `loaded` / `loading` / `unloaded` |
| `POST` | `/models/load` | `{"model": ...}`; starts a managed server (admin) |
| `POST` | `/models/unload` | `{"model": ...}`; stops a managed server (admin) |
| `GET` | `/health` | Gateway health |
| any | `/<path>` | Forwarded to the selected server's `/<path>` |

Extension fields on each model entry (not in llama-server; same shape as `/openai/v1/models`):
`context_length`, `architecture.input_modalities` / `output_modalities` (omitted while
vision support is unknown), and `reasoning.supported_efforts` / `default_effort`
(omitted when the model allows no efforts).

Model selection:

- **POST**: the JSON body's `model` field
- **GET**: `?model=<name>`
- Optional when only one server exists; otherwise `400`

The `model` value is rewritten to the upstream model id before forwarding, so
remote servers that are themselves in router mode still resolve it.

```bash
BASE=http://localhost:8010/llamacpp

curl $BASE/v1/models
curl $BASE/props?model=granite-4.1-3b-Q8_0
curl $BASE/tokenize -d '{"model": "granite-4.1-3b-Q8_0", "content": "hello"}'
curl $BASE/completion -d '{"model": "granite-4.1-3b-Q8_0", "prompt": "1, 2, 3,", "n_predict": 8}'
```

`/models/load` and `/models/unload` need an admin session when auth is enabled
(`Authorization: Bearer <token>` from `/api/auth/login`). Remote servers can't be
loaded or unloaded.
