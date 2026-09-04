# API Surface

Metallama exposes a REST API (`/api/*`), an Ollama-compatible gateway (`/ollama/*`),
and an OpenAI-compatible gateway (`/ollama/v1/*`). Mutating endpoints are guarded by
`admin_guard` (auth disabled by default).

## REST API (`/api/*`)

### Auth
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | Login with password → `{token, expires}` |
| POST | `/api/auth/logout` | Revoke a session token |
| GET | `/api/auth/status` | Whether auth is enabled |
| GET | `/api/auth/verify` | Validate a `Bearer` token |

### Health & System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Binary availability + auth-enabled status |
| GET | `/api/system/vram` | Current VRAM usage. Each GPU annotated with `tracked`; aggregate sums only tracked GPUs |
| GET | `/api/system/ram` | Current RAM usage (psutil) |
| GET | `/api/system/vram/gpus` | List available GPUs with their `tracked` state |
| POST | `/api/system/vram/gpus/toggle` | Toggle whether a GPU is tracked (persisted in `.metallama_gpu_config.json`) |
| GET | `/api/system/vram/history` | VRAM history (500 samples) + per-GPU history under `gpus`. The aggregate `history` is computed on-demand from the per-GPU histories of currently-tracked GPUs, so untracking a GPU also removes its past data from the total |
| GET | `/api/system/ram/history` | RAM history (500 samples) |
| GET | `/api/ports/suggest` | Suggest a free port |

### Models
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/models` | List managed + remote models with status |
| POST | `/api/models/{name}/start` | Start a managed server |
| POST | `/api/models/{name}/stop` | Stop a managed server |
| POST | `/api/models/create` | Create a managed or remote server |
| DELETE | `/api/models/{name}` | Delete a managed or remote server |
| GET | `/api/models/{name}/status` | Status of one model |
| GET | `/api/models/{name}/slots` | Proxy to upstream `/slots` |
| GET | `/api/models/{name}/logs` | Captured server logs (incremental/tail) |
| POST | `/api/models/{name}/auto-start` | Toggle auto-start on launch |
| GET | `/api/models/{id}/command` | Preview the launch command |
| POST | `/api/models/{name}/config` | Update managed server config. If running, requires `restart: "now"` or `"when_free"` to save+restart |
| POST | `/api/remote-servers/{name}/config` | Update remote server config |

### Engine Defaults
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/engine-defaults` | Get engine default args |
| POST | `/api/engine-defaults` | Set engine default args |

### Library & Model Files
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/library` | Inventory of models dir (GGUFs + partials, with `downloaded_at`, newest first) |
| POST | `/api/library/partials/discard` | Delete a `.partial` file |
| POST | `/api/library/partials/rename` | Rename a `.partial` file (and its `.meta` sidecar) |
| POST | `/api/library/models/delete` | Delete a `.gguf` model file |
| POST | `/api/library/models/rename` | Rename a `.gguf` model file (updates referencing server configs) |
| GET | `/api/model-files` | List `.gguf` files in models dir |

### HuggingFace
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/hf/search` | Search HF Hub for GGUF repos |
| GET | `/api/hf/models/{ns}/{repo}/files` | List `.gguf` files in a repo |
| POST | `/api/hf/download` | Download models (NDJSON progress stream) |

## Ollama Gateway (`/ollama/*`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tags` | List healthy models with details; vision models include `"vision"` and `"clip"`, while enabled reasoning efforts appear as `name:effort` variants |
| GET | `/api/ps` | List running (healthy) models |
| GET | `/api/version` | Gateway version |
| POST | `/api/show` | Model info/details. Vision models include `"vision"` capability + `"clip"` family |
| POST | `/api/chat` | Chat (streaming NDJSON or JSON). Virtual suffixes and explicit reasoning values are translated downstream; base64 images become OpenAI multimodal content parts |
| POST | `/api/generate` | Generate (streaming NDJSON or JSON) |
| POST | `/api/pull` | Stubbed — not supported |
| POST | `/api/push` | Stubbed — not supported |
| POST | `/api/copy` | Stubbed — not supported |
| POST | `/api/delete` | Stubbed — not supported |

**Reasoning effort** (`/api/chat`): values may be selected through enabled virtual
models such as `name:low`, or sent top-level/in `options`. The gateway strips the
suffix and injects `reasoning_effort`, `reasoning_budget`, and
`chat_template_kwargs.reasoning_effort`. `none`/`0` → `none`/0, `low` → 1024,
`medium` → 4096, and `high`/`xhigh` → -1. Virtual values are restricted to the
intersection of configured efforts and values inferred from the upstream template.

## OpenAI Gateway (`/ollama/v1/*`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/models` | List healthy models and enabled virtual effort variants (meta includes `vision`) |
| POST | `/v1/chat/completions` | Passthrough (streaming or JSON) |
| POST | `/v1/completions` | Passthrough |
| POST | `/v1/embeddings` | Passthrough |

## See Also
- [Architecture](architecture.md)
- [Ollama routes](../tree/app-ollama-routes.md)
- [app tree](../tree/app.md)