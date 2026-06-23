from __future__ import annotations

import asyncio
import signal
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .auth import admin_guard, auth_enabled, check_password, create_session, revoke_session
from .config import STATIC_DIR, Config
from .hf_routes import router as hf_router
from .models import ProcessState
from .ollama.config import load_config as load_ollama_config
from .ollama.probe import probe_subservers
from .ollama.registry import init_registry as init_ollama_registry
from .ollama.routes.ollama import router as ollama_router
from .ollama.routes.openai import router as openai_router
from .profiles import MODEL_PROFILES
from .runtime import (
    binary_health,
    build_command,
    build_command_preview,
    cleanup_dead,
    is_alive,
    model_locks,
    model_payload,
    runtime_processes,
)

app = FastAPI(title="metallama")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# Ollama / OpenAI gateway (mounted at /ollama)
# ---------------------------------------------------------------------------

_ollama_cfg = load_ollama_config()
init_ollama_registry(_ollama_cfg)
app.include_router(ollama_router, prefix="/ollama")
app.include_router(openai_router, prefix="/ollama")
app.include_router(hf_router)

# Server-side history storage (500 samples at 1s = ~8 minutes)
MAX_HISTORY_SAMPLES = 500
vram_history: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY_SAMPLES)
ram_history: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY_SAMPLES)


def server_profiles(service: str | None = None) -> dict[str, Any]:
    return dict(MODEL_PROFILES)


def servers_payload(service: str | None = None) -> list[dict[str, Any]]:
    return [model_payload(profile) for profile in server_profiles(service).values()]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/config")
def get_config() -> dict[str, str]:
    return {
        "EXECUTABLE_LLAMA": str(Config.EXECUTABLE_LLAMA),
        "BASE_URL": str(Config.BASE_URL),
    }


@app.get("/api/health")
def health_check() -> dict[str, Any]:
    """Return health status including binary availability."""
    return {
        "binaries": binary_health(),
        "auth_enabled": auth_enabled(),
    }


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.post("/api/auth/login")
def auth_login(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if not auth_enabled():
        return {"ok": True, "token": "", "auth_enabled": False}
    password = payload.get("password", "")
    if not password:
        raise HTTPException(status_code=400, detail="Password required")
    if not check_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")
    token, expires = create_session()
    return {"ok": True, "token": token, "expires": expires, "auth_enabled": True}


@app.post("/api/auth/logout")
def auth_logout(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    token = payload.get("token", "")
    if token:
        revoke_session(token)
    return {"ok": True}


@app.get("/api/auth/status")
def auth_status() -> dict[str, Any]:
    return {"auth_enabled": auth_enabled()}


@app.get("/api/auth/verify")
def auth_verify(authorization: str = Header("")) -> dict[str, Any]:
    if not auth_enabled():
        return {"valid": True}
    if not authorization.startswith("Bearer "):
        return {"valid": False}
    from .auth import validate_session
    token = authorization[7:]
    return {"valid": validate_session(token)}


@app.get("/api/system/vram")
def get_vram_status() -> dict[str, Any]:
    """Get current VRAM usage from nvidia-smi."""
    try:
        result = subprocess.run(
            ["/usr/bin/nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {"error": "nvidia-smi failed", "available": False}
        
        # Parse output: "used, total" (in MiB)
        lines = result.stdout.strip().split("\n")
        gpus = []
        for line in lines:
            if not line.strip():
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                used_mb = float(parts[0].strip())
                total_mb = float(parts[1].strip())
                gpus.append({
                    "used_gb": round(used_mb / 1024, 2),
                    "total_gb": round(total_mb / 1024, 2),
                    "used_mb": int(used_mb),
                    "total_mb": int(total_mb),
                    "percent": round((used_mb / total_mb * 100) if total_mb > 0 else 0, 1),
                })
        
        # Store in history (aggregate across GPUs)
        if gpus:
            total_used = sum(gpu["used_gb"] for gpu in gpus)
            total_max = sum(gpu["total_gb"] for gpu in gpus)
            avg_percent = sum(gpu["percent"] for gpu in gpus) / len(gpus)
            vram_history.append({
                "timestamp": int(time.time() * 1000),
                "percent": round(avg_percent, 1),
                "used_gb": round(total_used, 2),
                "total_gb": round(total_max, 2),
            })
        
        return {"available": True, "gpus": gpus}
    except FileNotFoundError:
        return {"error": "nvidia-smi not found", "available": False}
    except subprocess.TimeoutExpired:
        return {"error": "nvidia-smi timeout", "available": False}
    except Exception as exc:
        return {"error": str(exc), "available": False}


@app.get("/api/system/ram")
def get_ram_status() -> dict[str, Any]:
    """Get current RAM usage."""
    try:
        import psutil
        mem = psutil.virtual_memory()
        used_gb = round(mem.used / (1024**3), 2)
        total_gb = round(mem.total / (1024**3), 2)
        percent = round(mem.percent, 1)
        
        # Store in history
        ram_history.append({
            "timestamp": int(time.time() * 1000),
            "percent": percent,
            "used_gb": used_gb,
            "total_gb": total_gb,
        })
        
        return {
            "available": True,
            "used_gb": used_gb,
            "total_gb": total_gb,
            "percent": percent,
        }
    except ImportError:
        return {"error": "psutil not installed", "available": False}
    except Exception as exc:
        return {"error": str(exc), "available": False}


@app.get("/api/system/vram/history")
def get_vram_history() -> dict[str, Any]:
    """Get VRAM usage history."""
    return {"history": list(vram_history)}


@app.get("/api/system/ram/history")
def get_ram_history() -> dict[str, Any]:
    """Get RAM usage history."""
    return {"history": list(ram_history)}


@app.get("/api/model-files")
def list_model_files() -> dict[str, Any]:
    """Scan METALLAMA_MODELS_DIR for .gguf files and return their paths."""
    models_dir = Config.MODELS_DIR
    if not models_dir or not Path(models_dir).is_dir():
        return {"files": [], "models_dir": models_dir}
    models_path = Path(models_dir)
    files = sorted(
        str(p.relative_to(models_path)) for p in models_path.rglob("*.gguf")
    )
    return {"files": files, "models_dir": str(models_path)}


@app.get("/api/models")
async def list_models() -> dict[str, Any]:
    from .unified_config import load_unified_config
    from .ollama.probe import probe_one
    from .ollama.schemas import SubserverConfig
    import httpx

    managed = [model_payload(profile) for profile in MODEL_PROFILES.values()]
    cfg = load_unified_config()
    remote = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
        for srv_cfg in cfg.remote_servers:
            srv = SubserverConfig(name=srv_cfg.name, url=srv_cfg.url, context_length=srv_cfg.context_length)
            await probe_one(srv, client)
            remote.append({
                "id": srv_cfg.name,
                "display_name": srv_cfg.name,
                "url": srv_cfg.url,
                "status": "online" if srv.reachable else "offline",
                "managed": False,
                "port": None,
                "pid": None,
                "context_window": srv.context_length,
                "parallel": None,
                "extra_args": [],
                "model_found": True,
            })
    return {"models": managed + remote}


@app.get("/api/llm/servers")
def list_llm_servers() -> dict[str, Any]:
    return {"servers": servers_payload()}


@app.get("/api/servers")
def list_servers() -> dict[str, Any]:
    return {"servers": servers_payload()}


@app.get("/api/llm/servers/status")
def list_llm_servers_status() -> dict[str, Any]:
    return {
        "servers": [
            {"id": payload["id"], "status": payload["status"], "pid": payload["pid"], "url": payload["url"]}
            for payload in servers_payload()
        ]
    }


@app.get("/api/servers/status")
def list_servers_status() -> dict[str, Any]:
    return {
        "servers": [
            {"id": payload["id"], "status": payload["status"], "pid": payload["pid"], "url": payload["url"]}
            for payload in servers_payload()
        ]
    }


@app.get("/api/llm/servers/{server_id}/status")
def llm_server_status(server_id: str) -> dict[str, Any]:
    profile = server_profiles().get(server_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown server id")
    return model_payload(profile)


@app.get("/api/servers/{server_id}/status")
def server_status(server_id: str) -> dict[str, Any]:
    profile = server_profiles().get(server_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown server id")
    return model_payload(profile)


@app.post("/api/models/{model_name}/start")
async def start_model(model_name: str, _guard: None = Depends(admin_guard)) -> dict[str, Any]:
    profile = MODEL_PROFILES.get(model_name)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model")

    async with model_locks.setdefault(model_name, asyncio.Lock()):
        cleanup_dead(model_name)

        existing = runtime_processes.get(model_name)
        if existing and is_alive(existing.process):
            raise HTTPException(status_code=409, detail="Already running")

        command = build_command(profile)
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=f"Binary not found: {command[0]}") from exc

        runtime_processes[model_name] = ProcessState(
            process=proc,
            started_at=time.time(),
            command=command,
        )

    return {"ok": True, "model": model_payload(profile)}


@app.post("/api/llm/servers/{server_id}/start")
async def start_llm_server(server_id: str, _guard: None = Depends(admin_guard)) -> dict[str, Any]:
    profile = server_profiles().get(server_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown server id")
    result = await start_model(server_id)
    return {"ok": result["ok"], "server": result["model"]}


@app.post("/api/servers/{server_id}/start")
async def start_server(server_id: str, _guard: None = Depends(admin_guard)) -> dict[str, Any]:
    profile = server_profiles().get(server_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown server id")
    result = await start_model(server_id)
    return {"ok": result["ok"], "server": result["model"]}


@app.post("/api/models/{model_name}/stop")
async def stop_model(model_name: str, _guard: None = Depends(admin_guard)) -> dict[str, Any]:
    profile = MODEL_PROFILES.get(model_name)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model")

    async with model_locks.setdefault(model_name, asyncio.Lock()):
        cleanup_dead(model_name)
        state = runtime_processes.get(model_name)
        if not state:
            return {"ok": True, "model": model_payload(profile)}

        proc = state.process
        if is_alive(proc):
            proc.terminate()
            for _ in range(20):
                if not is_alive(proc):
                    break
                await asyncio.sleep(0.25)
            if is_alive(proc):
                proc.kill()

        runtime_processes.pop(model_name, None)

    return {"ok": True, "model": model_payload(profile)}


@app.post("/api/llm/servers/{server_id}/stop")
async def stop_llm_server(server_id: str, _guard: None = Depends(admin_guard)) -> dict[str, Any]:
    profile = server_profiles().get(server_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown server id")
    result = await stop_model(server_id)
    return {"ok": result["ok"], "server": result["model"]}


@app.post("/api/servers/{server_id}/stop")
async def stop_server(server_id: str, _guard: None = Depends(admin_guard)) -> dict[str, Any]:
    profile = server_profiles().get(server_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown server id")
    result = await stop_model(server_id)
    return {"ok": result["ok"], "server": result["model"]}


@app.post("/api/models/create")
async def create_model(payload: dict[str, Any] = Body(...), _guard: None = Depends(admin_guard)) -> dict[str, Any]:
    from .profiles import reload_model_profiles
    from .unified_config import add_managed_server

    model_type = payload.pop("type", "managed")
    if model_type == "managed":
        if not payload.get("name"):
            raise HTTPException(status_code=400, detail="name is required")
        if not payload.get("port"):
            raise HTTPException(status_code=400, detail="port is required")
        if not payload.get("model_path"):
            raise HTTPException(status_code=400, detail="model_path is required")
        server = add_managed_server(payload)
        reload_model_profiles()
        return {"ok": True, "name": server.name}
    elif model_type == "remote":
        if not payload.get("name"):
            raise HTTPException(status_code=400, detail="name is required")
        if not payload.get("url"):
            raise HTTPException(status_code=400, detail="url is required")
        from .unified_config import add_remote_server
        add_remote_server(payload)
        return {"ok": True, "name": payload["name"]}
    else:
        raise HTTPException(status_code=400, detail="type must be 'managed' or 'remote'")


@app.delete("/api/models/{model_name}")
async def delete_model(model_name: str, _guard: None = Depends(admin_guard)) -> dict[str, Any]:
    from .profiles import reload_model_profiles
    from .unified_config import delete_managed_server, delete_remote_server, load_unified_config

    # Try managed first
    if MODEL_PROFILES.get(model_name):
        async with model_locks.setdefault(model_name, asyncio.Lock()):
            cleanup_dead(model_name)
            state = runtime_processes.get(model_name)
            if state and is_alive(state.process):
                raise HTTPException(status_code=409, detail="Stop the server before deleting")
        delete_managed_server(model_name)
        reload_model_profiles()
        return {"ok": True, "deleted": model_name}

    # Try remote
    cfg = load_unified_config()
    if any(s.name == model_name for s in cfg.remote_servers):
        delete_remote_server(model_name)
        return {"ok": True, "deleted": model_name}

    raise HTTPException(status_code=404, detail="Unknown model")


@app.get("/api/models/{model_name}/status")
def model_status(model_name: str) -> dict[str, Any]:
    profile = MODEL_PROFILES.get(model_name)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model")
    return model_payload(profile)


@app.get("/api/models/{model_name}/slots")
async def model_slots(model_name: str) -> Any:
    """Proxy to a llama.cpp server's /slots endpoint.

    Works for both managed servers (looked up by port on 127.0.0.1) and
    remote servers (looked up by configured URL).
    Returns a compact list of slot statuses for UI indicators.
    """
    import httpx

    from .runtime import status_for
    from .unified_config import load_unified_config

    # Resolve the upstream /slots URL
    slots_url: str | None = None

    profile = MODEL_PROFILES.get(model_name)
    if profile:
        if status_for(profile) != "online":
            raise HTTPException(status_code=503, detail="Server not online")
        slots_url = f"http://127.0.0.1:{profile.port}/slots"
    else:
        # Try remote servers
        cfg = load_unified_config()
        srv_cfg = next((s for s in cfg.remote_servers if s.name == model_name), None)
        if not srv_cfg:
            raise HTTPException(status_code=404, detail="Unknown model")
        base = srv_cfg.url.rstrip("/")
        slots_url = f"{base}/slots"

    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(slots_url)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Upstream returned {resp.status_code}")
        data = resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Could not connect to server")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Server timed out")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch slots: {exc}")

    # Normalize: llama.cpp returns a list of slot objects
    slots = []
    if isinstance(data, list):
        for s in data:
            if not isinstance(s, dict):
                continue
            slots.append({
                "id": s.get("id"),
                "is_processing": bool(s.get("is_processing", False)),
                "n_ctx": s.get("n_ctx"),
                "n_prompt_tokens": s.get("n_prompt_tokens", 0),
                "n_decoded": s.get("n_decoded", 0),
                "speculative": bool(s.get("speculative", False)),
            })
    return {"slots": slots}


@app.on_event("startup")
async def probe_ollama_subservers() -> None:
    await probe_subservers()


@app.on_event("shutdown")
def stop_all_on_shutdown() -> None:
    for model_id, state in list(runtime_processes.items()):
        proc = state.process
        if is_alive(proc):
            proc.send_signal(signal.SIGTERM)
        runtime_processes.pop(model_id, None)


@app.get("/api/models/{model_id}/command")
def model_command_preview(model_id: str) -> dict[str, Any]:
    profile = MODEL_PROFILES.get(model_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model")
    command, binary_found = build_command_preview(profile)
    # Split compound args like "--temp 1.0" into individual tokens, then join.
    # All values come from trusted config, so plain space-join is safe.
    tokens = [token for arg in command for token in arg.split()]
    return {
        "command": " ".join(tokens),
        "binary_found": binary_found,
    }


@app.post("/api/models/{model_name}/config")
async def update_model_config(model_name: str, payload: dict[str, Any] = Body(...), _guard: None = Depends(admin_guard)) -> dict[str, Any]:
    from .profiles import reload_model_profiles
    from .unified_config import update_managed_server, load_unified_config

    profile = MODEL_PROFILES.get(model_name)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model")

    # Check if server is running - only allow changes when stopped
    async with model_locks.setdefault(model_name, asyncio.Lock()):
        cleanup_dead(model_name)
        state = runtime_processes.get(model_name)
        if state and is_alive(state.process):
            raise HTTPException(status_code=409, detail="Cannot change config while server is running")
    
    updates: dict[str, Any] = {}

    # Validate and collect name if provided
    if "name" in payload:
        new_name = payload["name"]
        if not isinstance(new_name, str) or not new_name.strip():
            raise HTTPException(status_code=400, detail="name must be a non-empty string")
        updates["name"] = new_name.strip()

    # Validate and collect model_path if provided
    if "model_path" in payload:
        mp = payload["model_path"]
        if not isinstance(mp, str):
            raise HTTPException(status_code=400, detail="model_path must be a string")
        updates["model_path"] = mp.strip()

    # Validate and collect context_window if provided
    if "context_window" in payload:
        context_window = payload["context_window"]
        if not isinstance(context_window, int) or context_window < 1:
            raise HTTPException(status_code=400, detail="context_window must be a positive integer")
        updates["context_window"] = context_window

    # Validate and collect parallel if provided
    if "parallel" in payload:
        parallel = payload["parallel"]
        if not isinstance(parallel, int) or parallel < 1:
            raise HTTPException(status_code=400, detail="parallel must be a positive integer")
        updates["parallel"] = parallel

    # Validate and collect port if provided
    if "port" in payload:
        port = payload["port"]
        if not isinstance(port, int) or port < 1024 or port > 65535:
            raise HTTPException(status_code=400, detail="port must be between 1024 and 65535")
        updates["port"] = port

    # Validate and collect extra_args if provided
    if "extra_args" in payload:
        extra_args = payload["extra_args"]
        if not isinstance(extra_args, list) or not all(isinstance(a, str) for a in extra_args):
            raise HTTPException(status_code=400, detail="extra_args must be a list of strings")
        updates["extra_args"] = extra_args

    # Validate and collect model_draft if provided
    if "model_draft" in payload:
        mtp = payload["model_draft"]
        if not isinstance(mtp, str):
            raise HTTPException(status_code=400, detail="model_draft must be a string")
        updates["model_draft"] = mtp.strip()

    if updates:
        # Update config.yaml (machine-managed section)
        update_managed_server(model_name, updates)
        # Reload profiles from disk so changes take effect immediately
        reload_model_profiles()
    
    # Return updated config from unified config
    unified = load_unified_config()
    server_entry = next((s for s in unified.managed_servers if s.name == model_name), None)
    return {
        "ok": True,
        "config": {
            "context_window": server_entry.context_window,
            "parallel": server_entry.parallel,
            "port": server_entry.port,
            "extra_args": server_entry.extra_args,
        } if server_entry else {},
    }


@app.post("/api/remote-servers/{server_name}/config")
async def update_remote_server_config(server_name: str, payload: dict[str, Any] = Body(...), _guard: None = Depends(admin_guard)) -> dict[str, Any]:
    from .unified_config import update_remote_server, load_unified_config

    cfg = load_unified_config()
    if not any(s.name == server_name for s in cfg.remote_servers):
        raise HTTPException(status_code=404, detail="Unknown remote server")

    updates: dict[str, Any] = {}
    if "name" in payload:
        new_name = payload["name"]
        if not isinstance(new_name, str) or not new_name.strip():
            raise HTTPException(status_code=400, detail="name must be a non-empty string")
        updates["name"] = new_name.strip()
    if "url" in payload:
        url = payload["url"]
        if not isinstance(url, str) or not url.strip():
            raise HTTPException(status_code=400, detail="url must be a non-empty string")
        updates["url"] = url.strip()

    if updates:
        update_remote_server(server_name, updates)

    unified = load_unified_config()
    entry = next((s for s in unified.remote_servers if s.name == (updates.get("name") or server_name)), None)
    return {"ok": True, "config": {"name": entry.name, "url": entry.url} if entry else {}}


@app.get("/api/engine-defaults")
def get_engine_defaults() -> dict[str, Any]:
    from .unified_config import load_unified_config
    cfg = load_unified_config()
    return {"defaults": cfg.engine_defaults}


@app.post("/api/engine-defaults")
def set_engine_defaults(payload: dict[str, Any] = Body(...), _guard: None = Depends(admin_guard)) -> dict[str, Any]:
    from .unified_config import load_unified_config, update_engine_defaults
    engine = payload.get("engine", "llama")
    args = payload.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise HTTPException(status_code=400, detail="args must be a list of strings")
    update_engine_defaults(engine, args)
    cfg = load_unified_config()
    return {"ok": True, "defaults": cfg.engine_defaults}




