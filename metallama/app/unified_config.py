from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Managed server (owned local model)
# ---------------------------------------------------------------------------

class ManagedServer(BaseModel):
    name: str
    model_path: str
    port: int
    engine: str = "llama"
    context_window: int | None = None
    parallel: int = 1
    extra_args: list[str] = Field(default_factory=list)

    @property
    def effective_display_name(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Remote server (distant, hand-edited)
# ---------------------------------------------------------------------------

class RemoteServer(BaseModel):
    name: str
    url: str
    family: str = "unknown"
    size: str = "unknown"
    context_length: int = 4096


# ---------------------------------------------------------------------------
# Root unified config
# ---------------------------------------------------------------------------

class UnifiedConfig(BaseModel):
    engine_defaults: dict[str, list[str]] = Field(default_factory=dict)
    managed_servers: list[ManagedServer] = Field(default_factory=list)
    remote_servers: list[RemoteServer] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_CONFIG_CACHE: dict[str, UnifiedConfig] = {}


def load_unified_config(path: str | Path = "config.yaml") -> UnifiedConfig:
    """Load the unified config.yaml from project root.

    If the file doesn't exist or sections are missing/malformed, returns a
    config with safe defaults so the server can still start.
    """
    config_path = Path(path)
    if not config_path.is_absolute():
        # Resolve relative to project root (two levels up from this file: app/ -> metallama/ -> project root).
        config_path = Path(__file__).resolve().parents[2] / config_path

    cache_key = str(config_path.resolve())
    if cache_key in _CONFIG_CACHE:
        return _CONFIG_CACHE[cache_key]

    if not config_path.exists():
        config = UnifiedConfig()
        _CONFIG_CACHE[cache_key] = config
        return config

    try:
        with config_path.open() as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception:
        config = UnifiedConfig()
        _CONFIG_CACHE[cache_key] = config
        return config

    # Use `or {}` / `or []` to handle None from YAML (e.g. key present but empty)
    engine_defaults_raw = raw.get("engine_defaults") or {}
    engine_defaults: dict[str, list[str]] = {}
    for engine_name, defaults in engine_defaults_raw.items():
        engine_defaults[engine_name] = defaults if isinstance(defaults, list) else []

    managed = [ManagedServer(**entry) for entry in (raw.get("managed_servers") or []) if entry]
    remote = [RemoteServer(**entry) for entry in (raw.get("remote_servers") or []) if entry]

    config = UnifiedConfig(
        engine_defaults=engine_defaults,
        managed_servers=managed,
        remote_servers=remote,
    )
    _CONFIG_CACHE[cache_key] = config
    return config


def clear_config_cache() -> None:
    """Clear the config cache (useful for regeneration workflows)."""
    _CONFIG_CACHE.clear()


def update_managed_server(server_id: str, updates: dict[str, Any], path: str | Path = "config.yaml") -> None:
    """Update fields on a managed_server entry in config.yaml.

    Typical usage: update_managed_server("llamacpp-coding", {"context_window": 128000})
    """
    config = load_unified_config(path)
    for i, server in enumerate(config.managed_servers):
        if server.name == server_id:
            for key, value in updates.items():
                if hasattr(server, key):
                    setattr(server, key, value)
            config.managed_servers[i] = server
            save_unified_config(config, path)
            return
    raise ValueError(f"Managed server '{server_id}' not found in config")


def update_remote_server(server_id: str, updates: dict[str, Any], path: str | Path = "config.yaml") -> None:
    """Update fields on a remote_server entry in config.yaml."""
    config = load_unified_config(path)
    for i, server in enumerate(config.remote_servers):
        if server.name == server_id:
            for key, value in updates.items():
                if hasattr(server, key):
                    setattr(server, key, value)
            config.remote_servers[i] = server
            save_unified_config(config, path)
            return
    raise ValueError(f"Remote server '{server_id}' not found in config")


def delete_managed_server(server_id: str, path: str | Path = "config.yaml") -> None:
    """Remove a managed_server entry from config.yaml."""
    config = load_unified_config(path)
    before = len(config.managed_servers)
    config.managed_servers = [s for s in config.managed_servers if s.name != server_id]
    if len(config.managed_servers) == before:
        raise ValueError(f"Managed server '{server_id}' not found in config")
    save_unified_config(config, path)


def delete_remote_server(server_id: str, path: str | Path = "config.yaml") -> None:
    """Remove a remote_server entry from config.yaml."""
    config = load_unified_config(path)
    before = len(config.remote_servers)
    config.remote_servers = [s for s in config.remote_servers if s.name != server_id]
    if len(config.remote_servers) == before:
        raise ValueError(f"Remote server '{server_id}' not found in config")
    save_unified_config(config, path)


def add_managed_server(data: dict[str, Any], path: str | Path = "config.yaml") -> ManagedServer:
    """Add a new managed_server entry to config.yaml."""
    config = load_unified_config(path)
    if any(s.name == data.get("name") for s in config.managed_servers):
        raise ValueError(f"Managed server '{data.get('name')}' already exists")
    server = ManagedServer(**data)
    config.managed_servers.append(server)
    save_unified_config(config, path)
    return server


def add_remote_server(data: dict[str, Any], path: str | Path = "config.yaml") -> RemoteServer:
    """Add a new remote_server entry to config.yaml."""
    config = load_unified_config(path)
    if any(s.name == data.get("name") for s in config.remote_servers):
        raise ValueError(f"Remote server '{data.get('name')}' already exists")
    server = RemoteServer(**data)
    config.remote_servers.append(server)
    save_unified_config(config, path)
    return server


def _yaml_str_value(value: Any) -> str:
    """Format a single value as a YAML scalar (quote strings that need it)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        needs_quote = value.lower() in ("true", "false", "null", "on", "off", "yes", "no")
        try:
            int(value)
            needs_quote = True
        except ValueError:
            pass
        try:
            float(value)
            needs_quote = True
        except ValueError:
            pass
        if any(c in value for c in (":", "#", "{", "}", "[", "]", ",", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`")):
            needs_quote = True
        if needs_quote:
            return f"'{value}'"
        return value
    return str(value)


def save_unified_config(config: UnifiedConfig, path: str | Path = "config.yaml") -> None:
    """Save the unified config back to YAML with comments preserved.

    Uses a template-based writer instead of yaml.dump() so that human-edited
    comments and section headers are preserved across saves.
    """
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = Path(__file__).resolve().parents[2] / config_path

    lines: list[str] = []
    lines.append("# Metallama Unified Configuration")
    lines.append("# =================================")
    lines.append("# This file is the single source of truth for all server configurations.")
    lines.append("#")
    lines.append("# Sections:")
    lines.append("#   engine_defaults  - Default parameters for llama.cpp servers (machine-managed)")
    lines.append("#   managed_servers  - Owned local models (machine-generated, can be regenerated)")
    lines.append("#   remote_servers   - Distant servers (hand-edited by humans)")
    lines.append("#")
    lines.append("# Machine-managed sections may contain auto-generated comments.")
    lines.append("# Remote servers section is safe for manual editing.")
    lines.append("")

    # --- engine_defaults ---
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Engine Defaults (Machine-Managed)")
    lines.append("# Default CLI args prepended to every server launch for this engine.")
    lines.append("# Last flag wins when merged with per-server args.")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("engine_defaults:")
    for engine_name, args in config.engine_defaults.items():
        lines.append(f"  {engine_name}:")
        if args:
            for arg in args:
                lines.append(f"    - {arg}")
        else:
            lines.append("    []")
    lines.append("")

    # --- managed_servers ---
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Managed Servers (Machine-Generated)")
    lines.append("# Local models owned by this project. Configuration is generated/managed")
    lines.append("# by the application. Manual edits may be overwritten on regeneration.")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("managed_servers:")
    for server in config.managed_servers:
        lines.append(f'  - name: "{server.name}"')
        lines.append(f'    model_path: "{server.model_path}"')
        lines.append(f"    port: {server.port}")
        if server.engine != "llama":
            lines.append(f'    engine: "{server.engine}"')
        lines.append(f"    context_window: {server.context_window}")
        lines.append(f"    parallel: {server.parallel}")
        if server.extra_args:
            lines.append("    extra_args:")
            for arg in server.extra_args:
                lines.append(f"      - {arg}")
        else:
            lines.append("    extra_args: []")
    lines.append("")

    # --- remote_servers ---
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Remote Servers (Hand-Edited)")
    lines.append("# Distant servers not owned by this project. Safe for manual editing.")
    lines.append("# These are read-only from the application's perspective.")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("remote_servers:")
    for server in config.remote_servers:
        lines.append(f'  - name: "{server.name}"')
        lines.append(f'    url: "{server.url}"')
        lines.append(f'    family: "{server.family}"')
        lines.append(f'    size: "{server.size}"')
        lines.append(f"    context_length: {server.context_length}")
    lines.append("")

    with config_path.open("w") as fh:
        fh.write("\n".join(lines))

    clear_config_cache()
