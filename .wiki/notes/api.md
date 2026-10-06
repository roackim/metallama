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
| `/ollama/api/generate` | POST | Generation through the chat template (`system`, `images`, `think`); `raw: true` bypasses it |
| `/ollama/api/embed` | POST | Embeddings (`input` str or list); needs a server started with `--embeddings` |
| `/ollama/api/embeddings` | POST | Legacy single-prompt embeddings |
| `/ollama` | GET/HEAD | "Ollama is running" health ping |

Ollama-compatibility notes: thinking is returned as `message.thinking` (chat) / `thinking`
(generate); `format` accepts `"json"` or a JSON schema; empty `messages`/`prompt` is a
load/unload ping answered locally (`done_reason: load|unload`); final `done` objects carry
token counts and durations from llama-server timings; errors under `/ollama/api/` use
Ollama's `{"error": "..."}` shape. `/api/show` capabilities (`tools`, `thinking`, `vision`)
come from the probed `/props`.

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

Streaming behaviour (for clients with a read timeout):
- A streamed request still waiting for upstream headers after 10 s (long prompt
  processing) is answered `200` early and gets `: keepalive` SSE comments every 10 s;
  the upstream stream is then relayed unchanged. Faster failures keep their real
  status. An upstream error after that point is sent as an OpenAI-shaped
  `data: {"error": …}` event followed by `data: [DONE]`.
- Streamed chat requests get `stream_options.include_usage: true` unless the client
  set it, so the stream ends with a usage chunk.
- A model server that can't be reached (loading, stopped) answers `503` (clients
  retry with backoff), not 502. There is no `/props` route on purpose: it would
  override per-model facts in clients that read it.

`/openai/v1/models` entries also carry `architecture: {input_modalities: ["text"] | ["text",
"image"], output_modalities: ["text"]}`, from the same probe as `meta.vision`. It is
**omitted** while vision is unknown (`vision_known` is false until `/props` has reported
modalities), because clients read absence as "unknown" and a list without `"image"` as a
definite no.

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

## llama.cpp native API (mounted at `/llamacpp`)

Shaped like llama-server's router mode (`--models-dir`): one base URL for every model.

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/llamacpp/models`, `/llamacpp/v1/models` | GET | — | All models with `status.value` = `loaded` / `loading` / `unloaded` |
| `/llamacpp/models/load` | POST | admin | `{"model": ...}` — start a managed server (remote → 400) |
| `/llamacpp/models/unload` | POST | admin | `{"model": ...}` — stop a managed server |
| `/llamacpp/health` | GET | — | Gateway health |
| `/llamacpp/{path}` | any | — | Forwarded to the server picked by body `model` (POST) or `?model=` (GET); `model` is rewritten to the upstream id. Required unless only one server exists. |

## See Also
- [Architecture overview](./architecture.md)
- [Main routes](../tree/app.md)
- [Gateway package](../tree/app-gateway.md)

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

- The gateway sends the level as `chat_template_kwargs.reasoning_effort` and `none` as
  `chat_template_kwargs.enable_thinking=false` (`gateway/reasoning.py`). llama-server
  ignores a top-level `reasoning_effort` (verified on b9923: `none` still thought).
  `minimal` / `max` map to the template's lowest / highest level when it lacks them.
  No token budget is sent (budgets hard-cut reasoning).
- A level outside the allowed set → `400 {"error", "allowed_efforts"}`. The allowed set
  is the configured list ∩ template support, or, with none configured, what the template
  supports (unknown values are always rejected).
- Listings advertise the allowed set (`reasoning_efforts` in `/api/tags`, `/api/show`,
  `/v1/models` meta) and the Ollama `thinking` capability. The base model is always
  listed; `name:effort` variants only when the server virtualizes efforts
  (`virtualize_efforts`, per managed server in `config.yaml`). Otherwise a suffixed
  name is 404 "model not found".
- Ollama responses carry reasoning in `message.thinking` (Ollama's native field).


## Reasoning replay (history reasoning)

Clients that store reasoning and send it back (moka's `replay_reasoning_depth`) rely on
the chat template rendering it, and by default most templates strip it from every turn
before the last user message. llama.cpp unifies the per-template switches
(`preserve_thinking`, `clear_thinking`, `truncate_history_thinking`, `drop_thinking`)
behind one template kwarg, `preserve_reasoning` (= `--reasoning-preserve`; `/props`
reports `chat_template_caps.supports_preserve_reasoning`; a no-op on templates without
it). `app/gateway/replay.py`, applied to every chat path (`/openai`, `/openrouter`,
`/ollama/api/chat`):

- Assistant `reasoning` / `reasoning_details` (OpenRouter) and `thinking` (Ollama) →
  `reasoning_content`, the only field llama-server reads. An existing
  `reasoning_content` wins; encrypted/signed blocks carry no text and are dropped.
- `chat_template_kwargs.preserve_reasoning` is decided, first match wins:
  1. client-set `chat_template_kwargs.preserve_reasoning`;
  2. top-level `preserve_reasoning` / `preserve_thinking` / `clear_thinking` boolean;
  3. the standard `reasoning.context` (OpenAI Responses, also OpenRouter):
     `all_turns` → true, `current_turn` → false, `auto`/absent → next rule;
  4. automatic: true when the history carries non-empty reasoning.
  `current_turn` still keeps the active turn's reasoning (templates only strip turns
  before the last user message), matching OpenAI's meaning.
- `/openai/v1/responses` (OpenAI's own way to replay reasoning): `reasoning` input items
  are rewritten to the only shape llama-server accepts (`summary: []` +
  `content: [{type: reasoning_text, text}]`; it 400s on anything else). Plaintext comes
  from `content`, else `summary`; items with none (cloud models' encrypted blobs) are
  dropped. llama-server emits the same shape, so verbatim echo of output items works.
  `previous_response_id` → 400 (stateless gateway: send the full `input`).
- **Ollama `/api/chat`:** Ollama's API has no parameter for preserving thinking (verified
  against `api/types.go` and its docs; see ollama#16240), so a standard Ollama client only
  gets the automatic rule: `thinking` on assistant messages → `reasoning_content`, flag on.
  As a **metallama extension, not part of Ollama's API**, the route also honours the
  same optional fields as `/openai`: `reasoning.context`, `preserve_reasoning` /
  `preserve_thinking` / `clear_thinking`, `chat_template_kwargs.preserve_reasoning`
  (same precedence). Only custom clients will send them.
- The depth itself stays the client's: turns sent without reasoning render as the
  template renders an empty one (Qwen: an empty `<think>` block). Requires a llama.cpp
  build with `preserve_reasoning` (`/props` → `chat_template_caps`).
- Verified on Qwen3.8-27B (prompt tokens, 2 assistant turns with reasoning): `all_turns`
  and auto 202, `current_turn` 71, no reasoning in history 79 (chat; same on /openrouter);
  Responses 214 / 83. Note this template already preserves when the variable is
  undefined, so `auto` equals a raw llama-server here; the flag matters for templates that
  strip by default (GLM-style) — not testable with the models on disk.

## Spec conformance notes

- Efforts vocabulary: `none, minimal, low, medium, high, xhigh, max` (union of llama.cpp,
  OpenRouter, Ollama `think`, DeepSeek). Which are accepted is still per-model.
- Mid-stream errors (after the early 200) use OpenRouter's documented shape: a chunk with
  top-level `error` and `finish_reason: "error"`, then `[DONE]`.
- Not emitted: OpenRouter `reasoning_details` blocks in responses (clients reading both it
  and `reasoning` could double-count), Ollama `/api/show` `thinking: {values, default}`.

## Contract tests

- `python tests/gateway_contract.py [--base URL] [--model NAME]` — live, against a running
  metallama with the model up (stdlib only). Covers, per gateway (`/openai/v1`,
  `/ollama/v1`, `/openrouter/v1`, `/ollama/api`): `/models` shape (ids unique,
  `context_length`, no nulls), SSE framing + final usage chunk + reasoning field name,
  non-stream, tool calls (streamed fragments + tool-result round trip), images, reasoning
  replay (`reasoning.context`), error statuses, Responses API, no `/props`; for Ollama:
  tags/show/ps/version, NDJSON stream, durations/counts, `done_reason`, tools, images,
  replay, generate, error shape.
- `uv run python tests/ollama_spec.py URL [MODEL]` — live Ollama API checks against
  ollama's docs/api.md (think levels, format schema, load/unload, generate templating,
  images, tools round trip, embed, error shape).
- `PYTHONPATH=. uv run python tests/gateway_failure_modes.py` — offline, fake upstream:
  keep-alives, 503 when the model server is unreachable, upstream status/message
  preserved, errors after the early 200, usage injection, request translation.

Ollama routes answer errors as `{"error": "message"}` with the real status (what Ollama
clients read), via a router-level route class; the other gateways use OpenAI's
`{"error": {"message", "type", "code"}}`. Ollama final messages carry
`total_duration`, `load_duration` (always 0), `prompt_eval_duration`, `eval_duration`
(from llama-server `timings`) plus counts and `done_reason`, on `/api/chat` and
`/api/generate`.

Responses carry the model id the client sent in `model` (llama-server reports its GGUF
path); this is rewritten per SSE line / JSON body on `/openai`, `/ollama/v1` and
`/openrouter`, including the final usage chunk and the Responses `response.model`.

### Model loading (observed on a real cold start, Qwen3.8-27B Q8, ~20 s)

llama-server answers `503 {"error": {"message": "Loading model", ...}}` while loading and
the gateways pass it through unchanged in their own error shape (`/openai`, `/openrouter`:
OpenAI shape; `/ollama/api`: `{"error": "Loading model"}`), with no keep-alive involved.
A request that arrives before the port is open gets the gateway's own `503` ("model
server unreachable"). `/openai/v1/models` and `/ollama/api/tags` list only servers whose
`/health` is OK, so a loading model is absent from the listings (empty `data` / `models`)
until it is ready; chat to it meanwhile returns the 503 above.
