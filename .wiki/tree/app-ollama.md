# metallama/app/ollama

Ollama-compatible gateway: registry of subservers, probing, schemas, and config
loading. Fans out requests to all registered llama.cpp servers.

## Files

| File | Purpose |
|------|---------|
| `registry.py` | In-memory registry of `SubserverConfig`; rebuild from all server sources |
| `probe.py` | Probe subservers (`/props`, `/v1/models`), detect vision, and infer supported reasoning efforts |
| `schemas.py` | Pydantic models: `SubserverConfig`, `AppConfig`, Ollama/OpenAI request schemas |
| `config.py` | Loads subserver config from unified config.yaml into `AppConfig` |
| `config.yaml` | Legacy subserver list (fallback source for the registry) |
| `__init__.py` | Empty package marker |

## Key Classes & Functions

| Name | File | What it does |
|------|------|-------------|
| `init_registry()` | registry.py | Replaces the registry from an `AppConfig` |
| `rebuild_registry()` | registry.py | Merges managed + remote + legacy subservers; carries over probed metadata by URL |
| `get_subserver()` | registry.py | Resolves a base or virtual `name:effort` model to its subserver |
| `get_all_subservers()` | registry.py | Returns all registered subservers |
| `split_virtual_model()` / `effective_reasoning_efforts()` | registry.py | Splits effort suffixes and computes enabled efforts intersected with template-supported efforts |
| `probe_one()` | probe.py | Probes a single subserver and backfills metadata in place, including vision and template-supported efforts |
| `probe_subservers()` | probe.py | Probes all subservers (called at startup) |
| `SubserverConfig` | schemas.py | Pydantic model for a gateway subserver, including vision and reasoning-effort state |
| `AppConfig` | schemas.py | Root config model holding a list of subservers |
| `OllamaChatRequest` / `OllamaGenerateRequest` / `OllamaShowRequest` | schemas.py | Ollama request schemas |
| `OpenAIChatRequest` / `OpenAICompletionRequest` / `OpenAIEmbeddingRequest` | schemas.py | OpenAI passthrough schemas |
| `load_config()` | config.py | Builds `AppConfig` from unified config.yaml |

## See Also
- [Ollama/OpenAI routes](../tree/app-ollama-routes.md)
- [Architecture overview](../notes/architecture.md)
- [API surface](../notes/api.md)