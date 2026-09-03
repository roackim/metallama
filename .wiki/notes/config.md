# Configuration

Metallama is configured via environment variables (`.env`) and a unified `config.yaml`
at the repo root.

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `METALLAMA_LLAMACPP_BINARY` | Path to `llama-server` binary (or name on `$PATH`) | _(empty — local servers won't start)_ |
| `METALLAMA_MODELS_DIR` | Directory for `.gguf` files (model picker & HF downloads) | _(empty — model picker disabled)_ |
| `METALLAMA_BASE_URL` | Display URL for model endpoint links | `http://localhost` |
| `METALLAMA_ADMIN_PASS_HASH` | Scrypt hash for admin login | _(empty — auth disabled)_ |
| `METALLAMA_CONFIG_FILE` | Path to the servers config | `config.yaml` (repo root) |
| `METALLAMA_DL_CONNECTIONS` | Parallel connections for HF downloads | `6` |
| `METALLAMA_BIND_HOST` | Address llama-servers bind to (`127.0.0.1` restricts to localhost) | `0.0.0.0` |

These are read in `config.py` (`Config` class) and `auth.py`. `METALLAMA_CONFIG_FILE`
is read in `unified_config.py`.

## config.yaml

The unified config file has three sections:

### `engine_defaults`
Default CLI args prepended to every server launch for a given engine. Last flag wins
when merged with per-server args. Example:
```yaml
engine_defaults:
  llama:
    - --gpu-layers all
    - --threads 4
    - --flash-attn on
```

### `managed_servers`
Owned local models, machine-generated/managed by the app. Each entry:
- `name` — server/model name
- `model_path` — path to the `.gguf` file
- `model_draft` — optional draft model path (speculative decoding)
- `port` — bind port
- `engine` — engine name (default `llama`)
- `context_window` — per-slot context length
- `parallel` — number of parallel slots
- `extra_args` — extra CLI args
- `auto_start` — whether to start on app startup

### `remote_servers`
Distant servers, hand-edited by humans. Each entry:
- `name` — server name
- `url` — base URL
- `family` / `size` — metadata (defaults `unknown`)
- `context_length` — context length (default `4096`)

## Legacy config

`metallama/app/ollama/config.yaml` holds a legacy `subservers` list. It is still read
as a fallback source for the gateway registry, but unified config wins on name conflicts.

## Loading & Caching

- `unified_config.load_unified_config()` loads and caches the config (keyed by resolved path).
- `clear_config_cache()` invalidates the cache after edits.
- `profiles.reload_model_profiles()` rebuilds `MODEL_PROFILES` from disk.
- `config.py` keeps thin compatibility wrappers (`load_server_configs`, `save_server_configs`, etc.) that delegate to `unified_config`.

## See Also
- [Architecture](architecture.md)
- [app tree](../tree/app.md)
- [root tree](../tree/root.md)