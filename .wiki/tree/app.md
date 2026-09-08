# metallama/app

Core application module — FastAPI app, authentication, configuration, runtime process management, and model profiles.

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Empty package marker |
| `main.py` | FastAPI application: routes for model lifecycle, config, system monitoring, auth, HF download, and static file serving |
| `auth.py` | Scrypt password hashing, session-based admin auth (`create_session`, `validate_session`, `AdminGuard`) |
| `config.py` | `Config` class with env-var-backed settings; backward-compat wrappers for server config |
| `models.py` | Dataclasses: `ModelProfile`, `ProcessState` |
| `profiles.py` | `MODEL_PROFILES` dict — built from `config.yaml` via `_build_profiles()`, not hardcoded |
| `unified_config.py` | `config.yaml` loader: `ManagedServer`, `RemoteServer`, `UnifiedConfig` models; load/save/clear cache |
| `hf.py` | HuggingFace Hub client: search models, list GGUF files, download with streaming |
| `hf_routes.py` | FastAPI router for HF search, file listing, and download endpoints |

## Key Classes & Functions

| Name | File | What it does |
|------|------|-------------|
| `Config` | config.py | Env-var-backed runtime configuration (`METALLAMA_LLAMACPP_BINARY`, `METALLAMA_BASE_URL`, `METALLAMA_MODELS_DIR`) |
| `ModelProfile` | models.py | Frozen dataclass: model identity, engine, port, args, context window, parallelism |
| `ProcessState` | models.py | Tracks a running subprocess with start time and command |
| `MODEL_PROFILES` | profiles.py | Dict of all model cards keyed by ID, built from `config.yaml` |
| `reload_model_profiles()` | profiles.py | Clears config cache and rebuilds `MODEL_PROFILES` from disk |
| `UnifiedConfig` | unified_config.py | Root config model: `engine_defaults`, `managed_servers`, `remote_servers` |
| `ManagedServer` | unified_config.py | Pydantic model for a local llama.cpp server entry |
| `RemoteServer` | unified_config.py | Pydantic model for a remote endpoint entry |
| `LlamaEngineDefaults` | unified_config.py | Structured llama.cpp flags with `to_cli_args()` converter |
| `build_command()` | runtime.py | Resolves binary + merges engine defaults + profile args → full command list |
| `model_payload()` | runtime.py | Serializes a `ModelProfile` to a dict for API responses |
| `status_for()` | runtime.py | Returns `"online"`, `"starting"`, or `"offline"` for a profile |
| `is_alive()` | runtime.py | Checks `proc.poll() is None` |
| `cleanup_dead()` | runtime.py | Removes stale entries from `runtime_processes` |
| `binary_health()` | runtime.py | Returns binary availability status for all engines |
| `model_locks` | runtime.py | Per-model `asyncio.Lock` dict (lazily created via `setdefault`) |
| `runtime_processes` | runtime.py | Dict mapping model_id → `ProcessState` |
| `AdminGuard` | auth.py | FastAPI dependency: validates Bearer token against in-memory session store |
| `hash_password()` | auth.py | Scrypt password hashing for `METALLAMA_ADMIN_PASS_HASH` |

## See Also
- [Architecture overview](../notes/architecture.md)
- [Configuration](../notes/config.md)
- [API reference](../notes/api.md)
- [Services & model profiles](../notes/services.md)
