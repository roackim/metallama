# Configuration

## Environment Variables

Loaded from `.env` file at project root via `python-dotenv`.

| Variable | Default | Description |
|----------|---------|-------------|
| `METALLAMA_LLAMACPP_BINARY` | `""` | Path (or name in `$PATH`) to the `llama-server` binary |
| `METALLAMA_MODELS_DIR` | `""` | Directory scanned for `.gguf` files (model picker & HF downloads) |
| `METALLAMA_BASE_URL` | `"http://gpu4.hygeos.com"` | Base URL shown in model endpoint links |
| `METALLAMA_ADMIN_PASS_HASH` | `""` | Scrypt password hash for admin login; empty = auth disabled |

## config.yaml (Unified Config)

Single source of truth at project root. Three sections:

```yaml
engine_defaults:
  llama:
    flash_attn: "on"
    threads: 6
    n_gpu_layers: 999
    cache_ram: 16384
    kv_unified: true
    # ...

managed_servers:    # Local llama.cpp instances (can also be added via API)
  - name: "my-model"
    model_path: "/path/to/model.gguf"
    port: 8081
    context_window: 64000
    parallel: 4
    extra_args:
      - --temp 0.85

remote_servers:     # Distant endpoints (hand-edited or added via API)
  - name: "remote-model"
    url: "http://other-host:8080"
    context_length: 32000
```

Loaded by `unified_config.py` into `UnifiedConfig` Pydantic model. Cached in memory; cache is cleared on any API write.

**Engine defaults** are prepended before profile `extra_args` (last flag wins in llama-server).

## Legacy Config

- `server_configs.json` — formerly used for per-server overrides; now superseded by `config.yaml`
- `metallama/app/ollama/config.yaml` — formerly used for ollama gateway subservers; now loaded from unified `config.yaml`

## See Also
- [Unified config module](../tree/app.md)
- [Ollama module](../tree/app-ollama.md)
- [Root files](../tree/root.md)
