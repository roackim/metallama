from __future__ import annotations

from .models import ModelProfile
from .unified_config import load_unified_config, clear_config_cache


def _build_profiles() -> dict[str, ModelProfile]:
    """Build MODEL_PROFILES dict from unified config.yaml managed_servers section."""
    config = load_unified_config()
    profiles: dict[str, ModelProfile] = {}
    for server in config.managed_servers:
        profiles[server.id] = ModelProfile(
            id=server.id,
            display_name=server.display_name,
            engine=server.engine,
            service=server.service,
            family=server.family,
            size=server.size,
            description=server.description,
            model_path=server.model_path,
            port=server.port,
            extra_args=server.extra_args,
            context_window=server.context_window,
            parallel=server.parallel,
        )
    return profiles


_MODEL_PROFILES: dict[str, ModelProfile] = _build_profiles()


def get_model_profiles() -> dict[str, ModelProfile]:
    """Get the current MODEL_PROFILES dict.

    This is a function rather than a bare dict so that callers can get
    a fresh copy after a config reload.
    """
    return _MODEL_PROFILES


def reload_model_profiles() -> dict[str, ModelProfile]:
    """Clear the config cache and rebuild MODEL_PROFILES from disk.

    Call this after updating config.yaml (e.g. from the API endpoint).
    Returns the new profiles dict.
    """
    clear_config_cache()
    global _MODEL_PROFILES
    _MODEL_PROFILES = _build_profiles()
    return _MODEL_PROFILES


# Backward-compatible alias: most code just imports MODEL_PROFILES directly.
MODEL_PROFILES: dict[str, ModelProfile] = _MODEL_PROFILES
