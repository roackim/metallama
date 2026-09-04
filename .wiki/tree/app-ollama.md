# metallama/app/ollama

Ollama-compatible gateway: registry of subservers, probing, schemas, and config
loading. Fans out requests to all registered llama.cpp servers.

## Files

| File | Purpose |
|------|---------|
| `registry.py` | In-memory registry of `SubserverConfig`; rebuild from all server sources |
| `probe.py` | Probe subservers (`/props`, `/v1/models`) and backfill metadata |
| `schemas.py` | Pydantic models: `SubserverConfig`, `AppConfig`, Ollama/OpenAI request schemas |
| `config.py` | Loads subserver config from unified config.yaml into `AppConfig` |
| `config.yaml` | Legacy subserver list (fallback source for the registry) |
| `__init__.py` | Empty package marker |

## Key Classes & Functions

| Name | File | What it does |
|------|------|-------------|
| `init_registry()` | registry.py | Replaces the registry from an `AppConfig` |
| `rebuild_registry()` | registry.py | Merges managed + remote + legacy subservers; carries over probed metadata by URL |
| `get_subserver()` | registry.py | Looks up a subserver by name or probed upstream model id |
| `get_all_subservers()` | registry.py | Returns all registered subservers |
| `probe_one()` | probe.py | Probes a single subserver and backfills metadata in place (incl. `vision` from `/props` → `modalities.vision`) |
| `probe_subservers()` | probe.py | Probes all subservers (called at startup) |
| `SubserverConfig` | schemas.py | Pydantic model for a gateway subserver (incl. `vision` flag) |
| `AppConfig` | schemas.py | Root config model holding a list of subservers |
| `OllamaChatRequest` / `OllamaGenerateRequest` / `OllamaShowRequest` | schemas.py | Ollama request schemas |
| `OpenAIChatRequest` / `OpenAICompletionRequest` / `OpenAIEmbeddingRequest` | schemas.py | OpenAI passthrough schemas |
| `load_config()` | config.py | Builds `AppConfig` from unified config.yaml |

## See Also
- [Ollama/OpenAI routes](../tree/app-ollama-routes.md)
- [Architecture overview](../notes/architecture.md)
- [API surface](../notes/api.md)