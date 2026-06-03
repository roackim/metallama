from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

SERVER_CONFIGS_PATH = PROJECT_ROOT / "server_configs.json"


class Config:
    EXECUTABLE_LLAMA = os.getenv("METALLAMA_LLAMACPP_BINARY", "")
    BASE_URL = os.getenv("METALLAMA_BASE_URL", "http://gpu4.hygeos.com")


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"


def load_server_configs() -> dict[str, Any]:
    """Load server configurations from server_configs.json."""
    if not SERVER_CONFIGS_PATH.exists():
        return {}
    
    try:
        with open(SERVER_CONFIGS_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_server_configs(configs: dict[str, Any]) -> None:
    """Save server configurations to server_configs.json."""
    try:
        with open(SERVER_CONFIGS_PATH, "w") as f:
            json.dump(configs, f, indent=2)
    except OSError as e:
        raise RuntimeError(f"Failed to save server configs: {e}")


def get_server_config(server_id: str) -> dict[str, Any]:
    """Get configuration for a specific server."""
    configs = load_server_configs()
    return configs.get(server_id, {})


def update_server_config(server_id: str, updates: dict[str, Any]) -> None:
    """Update configuration for a specific server."""
    configs = load_server_configs()
    if server_id not in configs:
        configs[server_id] = {}
    configs[server_id].update(updates)
    save_server_configs(configs)
