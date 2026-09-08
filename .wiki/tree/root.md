# Root Directory

Project root files: scripts, documentation, and configuration.

## Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Project metadata, dependencies (FastAPI, httpx, psutil, uvicorn, python-dotenv), hatchling build config, ruff settings |
| `README.md` | Project overview, setup guide, API reference, architecture notes |
| `config.yaml` | Unified server configuration — single source of truth for engine defaults, managed servers, and remote servers |
| `hash_password.py` | Helper to generate scrypt password hash for `METALLAMA_ADMIN_PASS_HASH` |
| `start.sh` | Shell script to start the server (with venv activated) |
| `ustart.sh` | Start script using `uv run` (preferred) |
| `.env` | Environment variables (binary paths, URLs, auth hash) — gitignored |
| `api.md` | CLI curl examples for the API |

## See Also
- [Configuration](../notes/config.md)
- [Architecture overview](../notes/architecture.md)
