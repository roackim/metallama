# API Reference

Base URL: `http://localhost:8010` (default)

## Servers

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/models` | List all servers with status |
| `GET` | `/api/models/{id}/status` | Single server status |
| `POST` | `/api/models/{id}/start` | Start a managed server |
| `POST` | `/api/models/{id}/stop` | Stop a managed server |
| `GET` | `/api/models/{id}/command` | Preview the llama.cpp launch command |
| `POST` | `/api/models/{id}/config` | Update managed server config |
| `POST` | `/api/models/create` | Add a managed or remote server |
| `DELETE` | `/api/models/{id}` | Delete a server |

## Gateways

Ollama (`/ollama`), OpenAI (`/openai/v1`) and native llama.cpp (`/llamacpp`)
client APIs, with their features, are documented in [gateways.md](./gateways.md).

## Auth & System

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Login (returns session token) |
| `POST` | `/api/auth/logout` | Revoke session |
| `GET` | `/api/auth/verify` | Validate current token |
| `GET` | `/api/health` | Binary availability & auth status |
| `GET` | `/api/system/vram` | Current VRAM usage |
| `GET` | `/api/system/ram` | Current RAM usage |
| `GET` | `/api/system/vram/history` | VRAM history (~8 min) |
| `GET` | `/api/system/ram/history` | RAM history (~8 min) |
| `GET` | `/api/model-files` | List `.gguf` files in models dir |

## HuggingFace

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/hf/search?q=…` | Search HF Hub for models |
| `GET` | `/api/hf/models/{ns}/{repo}/files` | List `.gguf` files in a repo |
| `POST` | `/api/hf/download` | Download files (streaming NDJSON) |
