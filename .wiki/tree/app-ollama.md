# metallama/app/ollama

Ollama/OpenAI-compatible gateway layer. Proxies requests from Ollama or OpenAI clients to upstream llama.cpp servers, with lazy probing for model metadata.

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Empty package marker |
| `config.py` | Loads unified `config.yaml` → `AppConfig` with `SubserverConfig` list (merges managed + remote) |
| `schemas.py` | Pydantic models for Ollama and OpenAI request/response schemas |
| `registry.py` | In-memory registry of subservers by name; `init_registry()`, `get_subserver()` |
| `probe.py` | Async probing of upstream servers: fetches `/props` and `/v1/models` to backfill metadata |
| `config.yaml` | Legacy YAML config listing subservers — now loaded from unified `config.yaml` |

## Key Classes & Functions

| Name | File | What it does |
|------|------|-------------|
| `SubserverConfig` | schemas.py | Pydantic model: name, url, size, family, parameter_size, context_length, upstream metadata |
| `AppConfig` | schemas.py | Container for list of `SubserverConfig` |
| `OllamaChatRequest` | schemas.py | Ollama chat request schema (model, messages, stream, options) |
| `OllamaGenerateRequest` | schemas.py | Ollama generate request schema (model, prompt, stream, options) |
| `OllamaShowRequest` | schemas.py | Ollama show request with model/name validation |
| `OpenAIChatRequest` | schemas.py | OpenAI chat completion request (extra fields allowed) |
| `OpenAICompletionRequest` | schemas.py | OpenAI completion request |
| `load_config()` | config.py | Merges managed_servers + remote_servers from unified config into `AppConfig` |
| `init_registry()` | registry.py | Populates global `_registry` dict from `AppConfig` |
| `REASONING_EFFORTS` | registry.py | Shared effort vocabulary: `none`, `low`, `medium`, `high`, `xhigh` |
| `split_virtual_model()` | registry.py | Splits `name:effort` into (base, effort) |
| `effective_reasoning_efforts()` | registry.py | Allowed efforts = configured whitelist ∩ template-supported |
| `resolve_reasoning_effort()` | registry.py | Picks a request's effort (request field > suffix) and raises 400 if not allowed |
| `virtual_efforts()` | registry.py | Efforts exposed as `name:effort` models (allowed set, or `[]` unless `virtualize_efforts`) |
| `template_reasoning_efforts()` | probe.py | Offline effort detection for a managed server: `--chat-template-file`, else GGUF `tokenizer.chat_template` (builtin `--chat-template` → `[]`) |
| `server_chat_template()` / `_infer_default_effort()` | probe.py | Offline template read; template default effort from `reasoning_effort\|default('x')` |
| `get_subserver()` | registry.py | Looks up subserver by model name or upstream_model_id (404 if missing) |
| `get_all_subservers()` | registry.py | Returns all registered subservers |
| `probe_one()` | probe.py | Probes a single upstream server, backfilling size, params, context_length, family |

## See Also
- [Ollama routes](./app-ollama-routes.md)
- [Architecture overview](../notes/architecture.md)
- [API reference](../notes/api.md)
