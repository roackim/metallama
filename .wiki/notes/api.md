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
| GET | `/api/system/vram` | Current VRAM usage (aggregated across GPUs) |
| GET | `/api/system/ram` | Current RAM usage (psutil) |
| GET | `/api/system/vram/history` | VRAM history (500 samples) |
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
| GET | `/api/tags` | List healthy models with details |
| GET | `/api/ps` | List running (healthy) models |
| GET | `/api/version` | Gateway version |
| POST | `/api/show` | Model info/details |
| POST | `/api/chat` | Chat (streaming NDJSON or JSON) |
| POST | `/api/generate` | Generate (streaming NDJSON or JSON) |
| POST | `/api/pull` | Stubbed — not supported |
| POST | `/api/push` | Stubbed — not supported |
| POST | `/api/copy` | Stubbed — not supported |
| POST | `/api/delete` | Stubbed — not supported |

## OpenAI Gateway (`/ollama/v1/*`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/models` | List healthy models |
| POST | `/v1/chat/completions` | Passthrough (streaming or JSON) |
| POST | `/v1/completions` | Passthrough |
| POST | `/v1/embeddings` | Passthrough |

## See Also
- [Architecture](architecture.md)
- [Ollama routes](../tree/app-ollama-routes.md)
- [app tree](../tree/app.md)