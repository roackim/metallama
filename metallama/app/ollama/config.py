from __future__ import annotations

from pathlib import Path

import yaml

from ..unified_config import load_unified_config
from .schemas import AppConfig, SubserverConfig


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    """Load subserver config from the unified config.yaml.

    Merges managed_servers (owned, local) and remote_servers (distant, hand-edited)
    into a single flat list of SubserverConfig entries for the ollama registry.
    """
    unified = load_unified_config()
    subservers: list[SubserverConfig] = []

    # Managed (owned) servers become subservers with localhost URLs.
    for server in unified.managed_servers:
        subservers.append(SubserverConfig(
            name=server.id,
            url=f"http://localhost:{server.port}",
            size=0,
            family=server.family,
            parameter_size=server.size,
            context_length=server.context_window or 4096,
        ))

    # Remote (distant) servers are passed through as-is.
    for server in unified.remote_servers:
        subservers.append(SubserverConfig(
            name=server.name,
            url=server.url,
            size=0,
            family=server.family,
            parameter_size=server.size,
            context_length=server.context_length,
        ))

    return AppConfig(subservers=subservers)
