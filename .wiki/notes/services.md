# Services & Model Profiles

Model profiles are built from `config.yaml` via `app/profiles.py`. The `_build_profiles()` function reads `ManagedServer` entries from the unified config and produces `MODEL_PROFILES` dict. Remote servers are handled separately in the API layer (not in `MODEL_PROFILES`).

## Server Types

| Type | Description | Config source |
|------|-------------|---------------|
| **Managed** | Local llama.cpp instance managed by metallama | `config.yaml` → `managed_servers` |
| **Remote** | Distant endpoint (hand-edited or added via API) | `config.yaml` → `remote_servers` |

## Engines

| Engine | Binary | Startup | Health Check |
|--------|--------|---------|-------------|
| `llama` | `METALLAMA_LLAMACPP_BINARY` (llama-server) | `--model {path} --host 0.0.0.0 --port {port}` | TCP port open |

## Engine Defaults

Defined in `config.yaml` under `engine_defaults`. `LlamaEngineDefaults` Pydantic model with `to_cli_args()`:

| Param | CLI Flag | Default |
|-------|----------|---------|
| `flash_attn` | `--flash-attn` | `on` |
| `threads` | `--threads` | `6` |
| `n_gpu_layers` | `--n-gpu-layers` | `999` |
| `cache_ram` | `--cache-ram` | `16384` |
| `kv_unified` | `--kv-unified` | `true` |
| `no_cont_batching` | `--no-cont-batching` | `true` |
| `sleep_idle_seconds` | `--sleep-idle-seconds` | `-1` |
| `fit` | `--fit` | `off` |

## Profile Configuration

Per-server overrides in `config.yaml`:
- `context_window` — context window size (multiplied by `parallel` for `--ctx-size`)
- `parallel` — number of parallel slots
- `extra_args` — additional CLI arguments appended after engine defaults

These are merged via `runtime.get_profile_with_config()` before command building.

## See Also
- [Profiles module](../tree/app.md)
- [Runtime module](../tree/app.md)
- [Configuration](./config.md)
