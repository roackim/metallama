from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


class Config:
    EXECUTABLE_LLAMA = os.getenv("METALLAMA_LLAMACPP_BINARY", "")
    BASE_URL = os.getenv("METALLAMA_BASE_URL", "http://gpu4.hygeos.com")


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"


# ---------------------------------------------------------------------------
# Compatibility wrappers — delegates to unified_config.
# Kept for backward compatibility; new code should import from unified_config directly.
# ---------------------------------------------------------------------------

def load_server_configs() -> dict[str, Any]:
    """Load managed server configs from unified config.yaml.

    Returns a dict keyed by server id with context_window and parallel.
    """
    from .unified_config import load_unified_config

    config = load_unified_config()
    result: dict[str, Any] = {}
    for server in config.managed_servers:
        result[server.id] = {
            "context_window": server.context_window,
            "parallel": server.parallel,
        }
    return result


def save_server_configs(configs: dict[str, Any]) -> None:
    """Save managed server configs to unified config.yaml.

    Expects a dict keyed by server id with context_window and/or parallel.
    """
    from .unified_config import load_unified_config, save_unified_config, clear_config_cache

    unified = load_unified_config()
    for server_id, values in configs.items():
        for server in unified.managed_servers:
            if server.id == server_id:
                if "context_window" in values:
                    server.context_window = values["context_window"]
                if "parallel" in values:
                    server.parallel = values["parallel"]
    save_unified_config(unified)
    clear_config_cache()


def get_server_config(server_id: str) -> dict[str, Any]:
    """Get configuration for a specific managed server from unified config.yaml."""
    configs = load_server_configs()
    return configs.get(server_id, {})


def update_server_config(server_id: str, updates: dict[str, Any]) -> None:
    """Update configuration for a specific managed server in unified config.yaml."""
    from .unified_config import load_unified_config, save_unified_config, clear_config_cache

    unified = load_unified_config()
    for server in unified.managed_servers:
        if server.id == server_id:
            if "context_window" in updates:
                server.context_window = updates["context_window"]
            if "parallel" in updates:
                server.parallel = updates["parallel"]
    save_unified_config(unified)
    clear_config_cache()
