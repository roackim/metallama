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

## OpenAI API (mounted at `/ollama`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ollama/v1/models` | GET | List models (OpenAI format) |
| `/ollama/v1/chat/completions` | POST | Chat completion passthrough |
| `/ollama/v1/completions` | POST | Completion passthrough |

## See Also
- [Architecture overview](./architecture.md)
- [Main routes](../tree/app.md)
- [Ollama routes](../tree/app-ollama-routes.md)
