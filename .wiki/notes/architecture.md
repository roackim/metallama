# Architecture

Metallama is a **llama.cpp process manager** — a single-process FastAPI application that manages llama.cpp model backends as child processes, exposes a web UI for management, and provides an Ollama/OpenAI-compatible API gateway for upstream LLM servers.

## Layers

```
┌─────────────────────────────────────────────────────────┐
│  Frontend (vanilla HTML/CSS/JS)                         │
│  /static/index.html + /static/js/                       │
├─────────────────────────────────────────────────────────┤
│  FastAPI Application                                    │
│  app/main.py — routes for:                              │
│    • Model lifecycle (start/stop/config/delete)         │
│    • Auth (login/logout/verify)                         │
│    • HuggingFace search & download                      │
│    • System monitoring (VRAM/RAM)                       │
│    • Static file serving                                │
├─────────────────────────────────────────────────────────┤
│  Unified Config (config.yaml)                           │
│  Single source of truth for:                            │
│    • engine_defaults (llama.cpp flags)                  │
│    • managed_servers (local models)                     │
│    • remote_servers (distant endpoints)                 │
├─────────────────────────────────────────────────────────┤
│  Ollama / OpenAI Gateway (app/ollama/)                  │
│  Mounted at /ollama, proxies to upstream servers:       │
│    • Ollama API: /api/tags, /api/chat, /api/generate…   │
│    • OpenAI API: /v1/chat/completions, /v1/models…      │
├─────────────────────────────────────────────────────────┤
│  Runtime (app/runtime.py)                               │
│  Process management: Popen, health checks, locks        │
├─────────────────────────────────────────────────────────┤
│  Backend Processes (child processes)                    │
│    • llama-server (LLM inference)                       │
└─────────────────────────────────────────────────────────┘
```

## Key Data Flows

### Model Start
1. Frontend calls `POST /api/models/{id}/start`
2. `runtime.py` acquires per-model async lock, builds command from profile + config
3. `subprocess.Popen` launches the backend binary
4. Status transitions: `offline` → `starting` → `online` (port health check)

### Ollama Gateway
1. Client calls `POST /ollama/api/chat` with model name
2. Registry resolves model → upstream server URL
3. Request proxied to upstream `/v1/chat/completions`
4. OpenAI SSE response translated to Ollama NDJSON format

## Single-Instance Rule
Each model profile has one process maximum. Start returns 409 if already running. Per-model `asyncio.Lock` prevents race conditions. Locks are lazily created for dynamically-added servers.

## Auth Model
- Optional — enabled when `METALLAMA_ADMIN_PASS_HASH` is set in `.env`
- Password verified via scrypt (same params as hash string)
- Session tokens stored in-memory (8-hour TTL)
- Frontend validates token every 5 seconds via `/api/auth/verify`
- Server restarts invalidate all sessions

## See Also
- [Model profiles & services](./services.md)
- [API reference](./api.md)
- [Configuration](./config.md)
