# metallama

A lightweight llama.cpp process manager with a web UI, Ollama-compatible gateway, and HuggingFace model browser.

- **Backend**: FastAPI (Python 3.11+)
- **Frontend**: vanilla HTML / CSS / JS (no build step)
- **Config**: single `config.yaml` at project root

## Features

- **Server management** — start / stop / configure llama.cpp instances from the web UI
- **Local & remote servers** — manage local llama.cpp processes *and* register remote endpoints in one place
- **Ollama-compatible API** — gateway at `/ollama` that fans out requests to all registered servers (`/ollama/api/tags`, `/ollama/api/chat`, `/ollama/api/generate`, `/ollama/v1/chat/completions`, …)
- **OpenAI-compatible API** — `/ollama/v1/models` and chat/completions passthrough
- **HuggingFace browser** — search HF Hub, list `.gguf` files, download models with streaming progress
- **System monitoring** — live VRAM (nvidia-smi) and RAM (psutil) gauges with history graphs
- **Admin authentication** — optional scrypt-based password login with session tokens
- **Dark / light theme** — toggle from the UI

## Requirements

- **Python ≥ 3.11**
- **llama-server** (llama.cpp) binary — only needed to run local models
- **nvidia-smi** — optional, for VRAM monitoring
- **uv** (recommended) or **pip** for dependency management

## Setup

### 1. Install dependencies

```bash
cd metallama
uv venv .venv
source .venv/bin/activate
uv pip install -e .
```

Or with plain pip:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Create a `.env` file

Create a `.env` file at the project root. Set theses keys:
```bash
# Path (or name in $PATH) to the llama-server binary
METALLAMA_LLAMACPP_BINARY=/path/to/llama-server

# Directory scanned for .gguf files (model picker & HF downloads)
METALLAMA_MODELS_DIR=/path/to/models

# Base URL shown in model endpoint links in the UI
METALLAMA_BASE_URL=http://localhost

# Admin password hash (leave unset to disable auth — see below)
# METALLAMA_ADMIN_PASS_HASH=scrypt$…
```

| Key | Purpose | Default |
|---|---|---|
| `METALLAMA_LLAMACPP_BINARY` | Path to `llama-server` binary | _(empty — local servers can't start)_ |
| `METALLAMA_MODELS_DIR` | Directory scanned for `.gguf` files | _(empty — model picker disabled)_ |
| `METALLAMA_BASE_URL` | Display URL for model endpoints | `http://gpu4.hygeos.com` |
| `METALLAMA_ADMIN_PASS_HASH` | Scrypt hash for admin login | _(empty — auth disabled)_ |

### 3. (Optional) Enable admin authentication

Auth is disabled by default. To password-protect admin actions (start / stop / create / delete / download):

```bash
# Generate a scrypt hash from your password
python hash_password.py
# → prompts for a password, prints the hash

# Add it to .env
echo 'METALLAMA_ADMIN_PASS_HASH=scrypt$…' >> .env
```

The web UI checks session validity every 5 seconds and auto-logs out if the server restarts or the session expires (8-hour TTL).

### 4. Define your servers

Edit `config.yaml` at the project root. It has three sections:

```yaml
# Default llama.cpp flags prepended to every local server launch
engine_defaults:
  llama:
    flash_attn: "on"
    threads: 6
    n_gpu_layers: 999
    # ...

# Local llama.cpp instances (managed by metallama)
managed_servers:
  - name: "my-model"
    model_path: "/path/to/model.gguf"
    port: 8081
    context_window: 64000
    parallel: 4
    extra_args:
      - --temp 0.85

# Remote endpoints (added via UI or hand-edited here)
remote_servers:
  - name: "remote-model"
    url: "http://other-host:8080"
    context_length: 32000
```

You can also add servers from the web UI (**+ Add Local Server** / **+ Add Remote Server**).

### 5. Start

```bash
./ustart.sh
```

This runs `uv run uvicorn app.main:app --app-dir metallama --host 0.0.0.0 --port 8010 --reload`.  
Open **http://localhost:8010**.

## API

### Models / servers

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/models` | List all servers (managed + remote) with status |
| `GET` | `/api/models/{id}/status` | Single server status |
| `POST` | `/api/models/{id}/start` | Start a managed server |
| `POST` | `/api/models/{id}/stop` | Stop a managed server |
| `GET` | `/api/models/{id}/command` | Preview the llama.cpp launch command |
| `POST` | `/api/models/{id}/config` | Update managed server config |
| `POST` | `/api/models/create` | Add a managed or remote server |
| `DELETE` | `/api/models/{id}` | Delete a server |

### Ollama gateway (`/ollama`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/ollama/api/tags` | List reachable models (Ollama-compatible) |
| `POST` | `/ollama/api/chat` | Chat completion (streams) |
| `POST` | `/ollama/api/generate` | Text generation (streams) |
| `POST` | `/ollama/api/show` | Model metadata |
| `GET` | `/ollama/v1/models` | OpenAI-compatible model list |
| `POST` | `/ollama/v1/chat/completions` | OpenAI-compatible chat |

### Auth

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/auth/status` | Is auth enabled? |
| `POST` | `/api/auth/login` | Login, returns session token |
| `POST` | `/api/auth/logout` | Revoke session |
| `GET` | `/api/auth/verify` | Validate current token |

### System

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Binary availability & auth status |
| `GET` | `/api/system/vram` | Current VRAM usage (nvidia-smi) |
| `GET` | `/api/system/ram` | Current RAM usage (psutil) |
| `GET` | `/api/system/vram/history` | VRAM history (last ~8 min) |
| `GET` | `/api/system/ram/history` | RAM history (last ~8 min) |
| `GET` | `/api/model-files` | List `.gguf` files in `METALLAMA_MODELS_DIR` |

### HuggingFace

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/hf/search?q=…` | Search HF Hub for models |
| `GET` | `/api/hf/models/{ns}/{repo}/files` | List `.gguf` files in a repo |
| `POST` | `/api/hf/download` | Download files (streaming NDJSON) |

## Project structure

```
metallama/
├── config.yaml              # Unified server configuration
├── pyproject.toml
├── start.sh / ustart.sh     # Launch scripts
├── hash_password.py         # Admin password hash generator
├── metallama/
│   └── app/
│       ├── main.py           # FastAPI app & routes
│       ├── auth.py           # Session-based auth (scrypt)
│       ├── config.py         # Env var config
│       ├── unified_config.py # config.yaml loader
│       ├── profiles.py       # MODEL_PROFILES builder
│       ├── runtime.py        # Process lifecycle & command builder
│       ├── models.py         # Dataclasses (ModelProfile, ProcessState)
│       ├── hf.py             # HuggingFace Hub client
│       ├── hf_routes.py      # HF API routes
│       ├── ollama/           # Ollama/OpenAI-compatible gateway
│       │   ├── registry.py   # Subserver registry
│       │   ├── probe.py      # Health probing
│       │   ├── schemas.py    # Pydantic models
│       │   ├── config.py     # Gateway config loader
│       │   └── routes/       # Ollama & OpenAI route handlers
│       └── static/           # Frontend (HTML/CSS/JS)
│           ├── index.html
│           ├── styles.css
│           └── js/
│               ├── main.js
│               ├── core/     # api, auth, clipboard, download
│               └── features/ # models, hf, system, theme
```

## Architecture

- Each managed server is a **child process** running `llama-server` (or compatible binary).
- A per-model **async lock** prevents concurrent start/stop race conditions.
- The Ollama gateway **probes** all registered servers on startup and lazily on request, routing to whichever are reachable.
- Config is **hot-reloadable** — edits via the API update `config.yaml` and refresh in-memory state without restarting metallama itself.

## License

See [LICENSE](LICENSE).
