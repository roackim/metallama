# Architecture

Metallama is a FastAPI application that manages llama.cpp server processes, downloads
GGUF models from HuggingFace, and exposes all servers behind a single Ollama/OpenAI
compatible gateway. The frontend is a vanilla JS single-page app with no build step.

## Layers

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (static/js) — vanilla ES modules, no build        │
│  core/ (api, auth, clipboard, download, uiMessage)          │
│  features/ (models, hf, library, connect, system, theme)    │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP (JSON / NDJSON / SSE)
┌───────────────────────────▼─────────────────────────────────┐
│  FastAPI app (metallama/app/main.py)                        │
│  - REST API (/api/*)                                        │
│  - Ollama gateway (/ollama/*)                               │
│  - OpenAI gateway (/ollama/v1/*)                            │
└───────┬──────────────────────────────┬──────────────────────┘
        │ spawns / manages            │ proxies
┌───────▼──────────────┐   ┌──────────▼───────────────────────┐
│  llama-server child  │   │  Remote llama.cpp servers        │
│  processes (managed) │   │  (configured via remote_servers) │
└──────────────────────┘   └──────────────────────────────────┘
```

## Key Data Flows

### Configuration
- `config.yaml` (repo root) is the single source of truth.
- `unified_config.py` loads it into `UnifiedConfig` (managed + remote servers, engine defaults) with caching.
- `profiles.py` builds `MODEL_PROFILES` (dict of `ModelProfile`) from `managed_servers`.
- `reload_model_profiles()` clears the config cache and rebuilds profiles after edits.

### Server lifecycle
- `main.py` start/stop endpoints acquire a per-model `asyncio.Lock` (`model_locks`).
- `runtime.build_command()` builds the llama-server CLI from the profile + engine defaults.
- `subprocess.Popen` spawns the server; `logs.begin_capture()` starts a daemon thread draining stdout.
- `runtime.status_for()` reports `offline` / `starting` / `online` (port open + `/health` 200).
- On shutdown, all running processes receive SIGTERM.

### Ollama/OpenAI gateway
- `ollama/registry.py` merges managed + remote + legacy subservers into `SubserverConfig` entries.
- `ollama/probe.py` probes each subserver (`/props`, `/v1/models`) to backfill metadata.
- `ollama/routes/ollama.py` translates Ollama requests → OpenAI shape, forwards to the upstream, and translates responses back (including tool calls and streaming).
- `ollama/routes/openai.py` is a passthrough for `/v1/*` endpoints.

### Model downloads (HuggingFace)
- `hf.py` searches the HF Hub, lists `.gguf` files, and downloads via parallel 32MB range requests.
- Progress is streamed as NDJSON; completed blocks are tracked in a `.partial.meta` sidecar for resumability.
- `hf_routes.py` exposes `/api/hf/*` endpoints.

### System monitoring
- `gpu.py` queries VRAM via nvidia-smi / rocm-smi / amd-smi (with absolute-path fallbacks for systemd's restricted PATH).
- `main.py` stores per-GPU VRAM history in bounded deques (500 samples) keyed by GPU id (`vram_gpu_history`). The aggregate total graph is computed on-demand from the per-GPU histories of currently-tracked GPUs, so untracking a GPU also removes its past data from the total. RAM history is a single bounded deque. Served via `/api/system/*`.

## Cross-Cutting Concerns

- **Shared HTTP client**: `http_client.py` provides a single process-wide `httpx.AsyncClient` to avoid per-request glibc heap growth (see `LLAMACPP_TENSOR_SPLIT_RAM_LEAK.md`).
- **Memory trimming**: `memtrim.py` periodically calls `malloc_trim` to return freed heap to the OS.
- **Auth**: `auth.py` guards mutating routes via the `admin_guard` dependency (see [security.md](security.md)).

## See Also
- [Config](config.md)
- [Security](security.md)
- [API surface](api.md)
- [Frontend](frontend.md)
- [app tree](../tree/app.md)
- [ollama tree](../tree/app-ollama.md)