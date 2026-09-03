# metallama/app

Core FastAPI backend: server process management, model library, HuggingFace
downloads, system monitoring, and the HTTP API surface.

## Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, route definitions, lifespan, startup/shutdown tasks |
| `auth.py` | Admin auth: scrypt password check, in-memory session tokens, `admin_guard` dependency |
| `config.py` | Env-var config (`Config` class) + thin compatibility wrappers delegating to `unified_config` |
| `unified_config.py` | Canonical loader/editor for `config.yaml` (managed/remote servers, engine defaults) |
| `profiles.py` | Builds `MODEL_PROFILES` from `managed_servers` in config.yaml |
| `models.py` | Dataclasses: `ModelProfile`, `ProcessState` |
| `runtime.py` | Process lifecycle: build commands, spawn/health/status, VRAM-fit estimates, load progress |
| `gguf.py` | GGUF header parser (metadata) + VRAM estimation |
| `gpu.py` | GPU memory querying (nvidia-smi / rocm-smi / amd-smi) |
| `hf.py` | HuggingFace Hub client: search, list GGUF files, parallel resumable downloads |
| `hf_routes.py` | `/api/hf/*` routes wrapping `hf.py` |
| `http_client.py` | Process-wide shared `httpx.AsyncClient` (avoids per-request heap growth) |
| `logs.py` | Per-server log capture (ring buffer + file), exit tracking |
| `memtrim.py` | Periodic `malloc_trim` to return freed heap to the OS |
| `__init__.py` | Empty package marker |

## Key Classes & Functions

| Name | File | What it does |
|------|------|-------------|
| `app` | main.py | The FastAPI application instance |
| `lifespan()` | main.py | Starts periodic malloc_trim; closes shared client on shutdown |
| `admin_guard` | auth.py | FastAPI dependency guarding mutating routes |
| `hash_password()` | auth.py | Produces a self-contained `scrypt$…` hash string |
| `check_password()` | auth.py | Verifies a plaintext password against the stored hash |
| `create_session()` / `validate_session()` | auth.py | Session token lifecycle (8h TTL) |
| `Config` | config.py | Env-var config (binary, base URL, models dir, bind host) |
| `load_unified_config()` | unified_config.py | Loads config.yaml with safe defaults + caching (lock-protected) |
| `save_unified_config()` | unified_config.py | Writes config.yaml atomically (temp file + `os.replace`), lock-protected |
| `update_managed_server()` | unified_config.py | Edits a managed server entry in config.yaml |
| `add_managed_server()` / `delete_managed_server()` | unified_config.py | Managed server CRUD |
| `add_remote_server()` / `update_remote_server()` | unified_config.py | Remote server CRUD |
| `update_engine_defaults()` | unified_config.py | Replaces default CLI args for an engine |
| `MODEL_PROFILES` | profiles.py | Dict of `ModelProfile` keyed by server name |
| `reload_model_profiles()` | profiles.py | Rebuilds profiles from disk after config edits |
| `ModelProfile` | models.py | Frozen dataclass describing a managed server |
| `ProcessState` | models.py | Running process + start time + command |
| `runtime_processes` / `model_locks` | runtime.py | Global runtime state and per-model async locks |
| `build_command()` | runtime.py | Builds the llama-server CLI command for a profile |
| `build_command_preview()` | runtime.py | Builds command for preview/clipboard (placeholder binary allowed) |
| `status_for()` | runtime.py | Returns offline/starting/online for a profile |
| `model_payload()` | runtime.py | Full model status dict for the UI |
| `vram_estimate_for()` | runtime.py | VRAM-fit estimate for a profile's current config |
| `read_metadata()` | gguf.py | Parses scalar/string KVs from a GGUF header (bounded LRU cache) |
| `estimate_vram_gb()` | gguf.py | Rough VRAM upper-bound estimate (weights + KV cache) |
| `detect_tool()` / `get_gpu_memory()` | gpu.py | GPU memory tool detection and querying |
| `vram_status()` | gpu.py | Payload for `/api/system/vram` |
| `search_models()` | hf.py | Search HF Hub for GGUF repos |
| `list_gguf_files()` | hf.py | List `.gguf` files in a repo with parsed metadata |
| `download_model()` | hf.py | NDJSON progress stream for parallel resumable downloads |
| `get_client()` / `shared_client()` | http_client.py | Shared `httpx.AsyncClient` access |
| `begin_capture()` | logs.py | Starts a daemon thread draining proc stdout to ring buffer + file |
| `ServerLog` | logs.py | Thread-safe ring buffer of `(seq, text)` log lines |
| `periodic_malloc_trim()` | memtrim.py | Periodically calls `malloc_trim` until cancelled |

## See Also
- [Architecture overview](../notes/architecture.md)
- [Config](../notes/config.md)
- [Security](../notes/security.md)
- [API surface](../notes/api.md)
- [Ollama gateway](../tree/app-ollama.md)