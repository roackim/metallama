# Metallama Wiki — Agent Contract

This file maps the source tree to wiki pages. Read it first before updating the wiki.

## Project Overview

Metallama is a lightweight web UI for managing llama.cpp servers, downloading GGUF
models from HuggingFace, and exposing everything behind a single Ollama-compatible
API gateway. Backend is FastAPI (Python ≥ 3.11); frontend is vanilla HTML/CSS/JS
(no build step). Served on port 8010 by default.

## Source → Tree Page Mapping

| Source directory | Tree page |
|------------------|-----------|
| `metallama/app/` | `.wiki/tree/app.md` |
| `metallama/app/ollama/` | `.wiki/tree/app-ollama.md` |
| `metallama/app/ollama/routes/` | `.wiki/tree/app-ollama-routes.md` |
| `metallama/app/static/js/core/` | `.wiki/tree/static-js-core.md` |
| `metallama/app/static/js/features/` | `.wiki/tree/static-js-features.md` |
| `metallama/app/static/` (html/css) | `.wiki/tree/static.md` |
| repo root (scripts, config) | `.wiki/tree/root.md` |

## Notes Pages

| Notes page | Covers |
|------------|--------|
| `.wiki/notes/architecture.md` | System overview, layers, key data flows |
| `.wiki/notes/config.md` | Env vars, config.yaml, defaults |
| `.wiki/notes/security.md` | Auth model, trust boundaries, secrets |
| `.wiki/notes/api.md` | Public HTTP API surface (REST + Ollama/OpenAI gateway) |
| `.wiki/notes/frontend.md` | Frontend structure, JS module layout, theming |

## Repo-Specific Conventions

- **Config source of truth**: `config.yaml` at repo root (unified config). The legacy
  `metallama/app/ollama/config.yaml` is still read as a fallback source for the gateway
  registry but unified config wins on name conflicts.
- **Config loading**: `metallama/app/unified_config.py` is the canonical loader. The
  `config.py` module keeps thin compatibility wrappers that delegate to it.
- **Model profiles**: `MODEL_PROFILES` in `profiles.py` is built from `managed_servers`
  in config.yaml. `reload_model_profiles()` must be called after config edits.
- **Runtime state**: `runtime_processes` and `model_locks` live in `runtime.py`.
- **Shared HTTP client**: `http_client.py` provides a process-wide `httpx.AsyncClient`
  to avoid per-request heap growth (see `LLAMACPP_TENSOR_SPLIT_RAM_LEAK.md`).
- **Auth**: scrypt password hash in `METALLAMA_ADMIN_PASS_HASH`; session tokens stored
  in-memory with 8h TTL. `admin_guard` dependency protects mutating routes.
- **Frontend**: ES modules under `static/js/`. `core/` has shared utilities; `features/`
  has one module per UI feature. `main.js` wires everything together.
- **Security fixes** are documented in `SECURITY_FIXES.md` at repo root.

## Update Rules

- One tree page per directory (not per file).
- Document what exists now — no aspirational statements.
- Don't duplicate notes content in tree pages; link instead.
- Append every change to `.wiki/log/update.log` with an ISO timestamp.