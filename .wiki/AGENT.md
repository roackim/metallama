# Metallama Wiki — Agent Contract

Repo-specific source→wiki mapping and conventions.

## Source Directories → Tree Pages

| Source directory | Tree page |
|---|---|
| `metallama/app/` (root module) | `tree/app.md` |
| `metallama/app/ollama/` | `tree/app-ollama.md` |
| `metallama/app/ollama/routes/` | `tree/app-ollama-routes.md` |
| `metallama/app/static/` | `tree/app-static.md` |
| `metallama/app/static/js/` | `tree/app-static-js.md` |
| `metallama/app/static/js/core/` | `tree/app-static-js-core.md` |
| `metallama/app/static/js/features/` | `tree/app-static-js-features.md` |
| Root-level scripts & config | `tree/root.md` |


## Notes Pages

| Notes page | Covers |
|---|---|
| `notes/architecture.md` | System overview, layers, data flows |
| `notes/config.md` | Environment variables, config files, defaults |
| `notes/api.md` | REST API surface (management + Ollama + OpenAI + Auth + HF) |
| `notes/services.md` | Model profiles, engines, and service types |

## Conventions

- Python 3.11+, FastAPI backend, vanilla HTML/CSS/JS frontend
- Package name: `metallama`, importable as `app` (hatchling maps `metallama/app`)
- Model profiles built from `config.yaml` via `app/profiles.py` (not hardcoded)
- Runtime state (processes, locks) lives in `app/runtime.py`
- Unified config (`config.yaml` at project root) is the single source of truth for server definitions
- Ollama/OpenAI gateway config is loaded from the unified config, not a separate `ollama/config.yaml`
- Admin auth is optional — enabled when `METALLAMA_ADMIN_PASS_HASH` env var is set
