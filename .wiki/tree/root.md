# Repo root

Top-level project files: scripts, config, docs, and packaging.

## Files

| File | Purpose |
|------|---------|
| `config.yaml` | Unified server configuration (single source of truth) |
| `hash_password.py` | CLI helper to generate a scrypt hash for admin auth |
| `start.sh` | Dev launcher: uvicorn with `--reload` on port 8010 |
| `ustart.sh` | Production launcher: `uv run uvicorn` on port 8010 |
| `pyproject.toml` | Packaging + deps (fastapi, httpx, psutil, dotenv, uvicorn) |
| `README.md` | Project overview, quick start, env var table |
| `SECURITY_FIXES.md` | Documented security hardening & runtime fixes |
| `LLAMACPP_TENSOR_SPLIT_RAM_LEAK.md` | Notes on a llama.cpp tensor-split RAM leak |
| `LICENSE` | Project license |
| `.env` | Local env vars (gitignored) |
| `logs/` | Captured llama-server logs (one file per server) |
| `.venv/` | Virtual environment (gitignored) |

## Key Details

- `config.yaml` sections: `engine_defaults`, `managed_servers` (machine-managed), `remote_servers` (hand-edited).
- `hash_password.py` prints a `METALLAMA_ADMIN_PASS_HASH=scrypt$…` line to append to `.env`.
- `start.sh` uses `--reload` for development; `ustart.sh` is the plain production run.

## See Also
- [Config](../notes/config.md)
- [Architecture overview](../notes/architecture.md)