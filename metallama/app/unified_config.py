from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Engine defaults – structured representation of llama.cpp flags
# ---------------------------------------------------------------------------

class LlamaEngineDefaults(BaseModel):
    flash_attn: str = "on"
    threads: int = 6
    n_gpu_layers: int = 999
    sleep_idle_seconds: int = -1
    fit: str = "off"
    no_cont_batching: bool = True
    cache_ram: int = 16384
    kv_unified: bool = True

    def to_cli_args(self) -> list[str]:
        """Convert structured defaults to flat CLI argument list."""
        args: list[str] = []
        mapping = [
            ("flash_attn", "--flash-attn"),
            ("threads", "--threads"),
            ("n_gpu_layers", "--n-gpu-layers"),
            ("sleep_idle_seconds", "--sleep-idle-seconds"),
            ("fit", "--fit"),
            ("cache_ram", "--cache-ram"),
        ]
        for attr, flag in mapping:
            value = getattr(self, attr)
            args.extend([flag, str(value)])

        # Boolean flags (present = enabled)
        if self.no_cont_batching:
            args.append("--no-cont-batching")
        if self.kv_unified:
            args.append("--kv-unified")

        return args


# ---------------------------------------------------------------------------
# Managed server (owned local model)
# ---------------------------------------------------------------------------

class ManagedServer(BaseModel):
    id: str
    display_name: str
    engine: str = "llama"
    service: str = "LLM"
    family: str = "unknown"
    size: str = "unknown"
    description: str = ""
    model_path: str
    port: int
    context_window: int | None = None
    parallel: int = 1
    extra_args: list[str] = Field(default_factory=list)


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
    engine_defaults: dict[str, LlamaEngineDefaults] = Field(default_factory=dict)
    managed_servers: list[ManagedServer] = Field(default_factory=list)
    remote_servers: list[RemoteServer] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_CONFIG_CACHE: dict[str, UnifiedConfig] = {}


def load_unified_config(path: str | Path = "config.yaml") -> UnifiedConfig:
    """Load the unified config.yaml from project root."""
    config_path = Path(path)
    if not config_path.is_absolute():
        # Resolve relative to project root (two levels up from this file: app/ -> metallama/ -> project root).
        config_path = Path(__file__).resolve().parents[2] / config_path

    cache_key = str(config_path.resolve())
    if cache_key in _CONFIG_CACHE:
        return _CONFIG_CACHE[cache_key]

    with config_path.open() as fh:
        raw = yaml.safe_load(fh) or {}

    engine_defaults_raw = raw.get("engine_defaults", {})
    engine_defaults = {}
    for engine_name, defaults in engine_defaults_raw.items():
        engine_defaults[engine_name] = LlamaEngineDefaults(**defaults)

    managed = [ManagedServer(**entry) for entry in raw.get("managed_servers", [])]
    remote = [RemoteServer(**entry) for entry in raw.get("remote_servers", [])]

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
        if server.id == server_id:
            for key, value in updates.items():
                if hasattr(server, key):
                    setattr(server, key, value)
            config.managed_servers[i] = server
            save_unified_config(config, path)
            return
    raise ValueError(f"Managed server '{server_id}' not found in config")


def _yaml_str_value(value: Any) -> str:
    """Format a single value as a YAML scalar (quote strings that need it)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        # Quote strings that could be misinterpreted (booleans, numbers, special chars).
        needs_quote = False
        lower = value.lower()
        if lower in ("true", "false", "null", "on", "off", "yes", "no"):
            needs_quote = True
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
    lines.append("# Default parameters applied to all llama.cpp servers unless overridden.")
    lines.append("# These are prepended before profile-specific args (last flag wins).")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("engine_defaults:")
    for engine_name, defaults in config.engine_defaults.items():
        lines.append(f"  {engine_name}:")
        for key, value in defaults.model_dump().items():
            lines.append(f"    {key}: {_yaml_str_value(value)}")
    lines.append("")

    # --- managed_servers ---
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Managed Servers (Machine-Generated)")
    lines.append("# Local models owned by this project. Configuration is generated/managed")
    lines.append("# by the application. Manual edits may be overwritten on regeneration.")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("managed_servers:")
    for server in config.managed_servers:
        lines.append(f'  - id: "{server.id}"')
        lines.append(f'    display_name: "{server.display_name}"')
        lines.append(f'    engine: "{server.engine}"')
        lines.append(f'    service: "{server.service}"')
        lines.append(f'    family: "{server.family}"')
        lines.append(f'    size: "{server.size}"')
        lines.append(f'    description: "{server.description}"')
        lines.append(f'    model_path: "{server.model_path}"')
        lines.append(f"    port: {server.port}")
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
