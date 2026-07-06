# Metallama

A lightweight web UI for managing llama.cpp servers, downloading models from HuggingFace, and exposing everything behind a single Ollama-compatible API gateway.

Built with FastAPI (Python 3.11+) and vanilla HTML/CSS/JS, no build.

## What It Does

- **Download GGUF models** — browse HuggingFace Hub, pick `.gguf` files, download with live speed, cancel/resume, and a one-click "create server" on completion
- **Spawn & manage llama.cpp instances** — start, stop, and configure local servers from a web UI, with live logs, load-progress bars, and crash diagnostics on every card
- **VRAM-fit estimates** — GGUF metadata is parsed locally to warn before you launch a model that won't fit
- **Unified Ollama-compatible gateway** — one `/ollama` endpoint fans out requests to all registered servers
- **Plug in remote servers** — point to llama.cpp instances on other machines and route through the same gateway
- **OpenAI-compatible API** — `/v1/chat/completions` and model listing work out of the box
- **Live system monitoring** — VRAM (NVIDIA, ROCm, or amd-smi) and RAM usage with history graphs
- **Optional admin auth** — scrypt-based password login with 8-hour sessions
- **Dark / light theme**

## Quick Start

### Requirements

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- `llama-server` binary (only needed for local models)
- `nvidia-smi`, `rocm-smi`, or `amd-smi` (optional, for VRAM monitoring and fit estimates)

### Install

```bash
cd metallama
uv venv .venv && source .venv/bin/activate
uv pip install -e .
```

### Configure

Create a `.env` file at the project root:

```bash
# Path to llama-server binary (or just the name if it's in $PATH)
METALLAMA_LLAMACPP_BINARY=/path/to/llama-server

# Directory for .gguf files (model picker & HF downloads)
METALLAMA_MODELS_DIR=/path/to/models

# Base URL shown in model endpoint links
METALLAMA_BASE_URL=http://localhost

# Admin password hash (leave unset to disable auth)
# METALLAMA_ADMIN_PASS_HASH=scrypt$…
```

| Variable | Purpose | Default |
|---|---|---|
| `METALLAMA_LLAMACPP_BINARY` | Path to `llama-server` | _(empty — local servers won't start)_ |
| `METALLAMA_MODELS_DIR` | Directory for `.gguf` files | _(empty — model picker disabled)_ |
| `METALLAMA_BASE_URL` | Display URL for endpoints | `http://localhost` |
| `METALLAMA_ADMIN_PASS_HASH` | Scrypt hash for admin login | _(empty — auth disabled)_ |
| `METALLAMA_CONFIG_FILE` | Path to the servers config | `config.yaml` (repo root) |
| `METALLAMA_DL_CONNECTIONS` | Parallel connections for HF downloads | `6` |
| `METALLAMA_BIND_HOST` | Address llama-servers bind to (`0.0.0.0` to expose on LAN) | `127.0.0.1` |

Captured llama-server logs are written to `logs/<server>.log` (rewritten on each start).


### Run

```bash
./ustart.sh
```

Then open **http://localhost:8010**.

### Optional: Enable Admin Auth

```bash
python hash_password.py    # prompts for a password, prints the hash
echo 'METALLAMA_ADMIN_PASS_HASH=scrypt$…' >> .env
```

## How It Works

- Each managed server runs as a child process (`llama-server` or compatible binary).
- An async lock prevents concurrent start/stop race conditions per model.
- The Ollama gateway probes all registered servers on startup and lazily on request, routing to whichever are reachable.
- Config is hot-reloadable — API edits update `config.yaml` and refresh in-memory state without restarting.

## License

See [LICENSE](LICENSE).
