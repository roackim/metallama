from __future__ import annotations

from fastapi import HTTPException

from .schemas import AppConfig, SubserverConfig

_registry: dict[str, SubserverConfig] = {}

# Recognized reasoning-effort values. A client can select e.g.
# "Qwen3.8-27B-Q8_0:high" to request a specific reasoning effort; the gateway
# strips the suffix, resolves the base server, and merges the effort params.
REASONING_EFFORTS = ("low", "medium", "high", "xhigh")


def split_virtual_model(model_name: str, efforts: frozenset[str] | tuple | set | None = None) -> tuple[str, str | None]:
    """Split a model name into (base_name, effort_suffix).

    `efforts` defaults to the recognized value set; when a server's configured
    efforts differ, pass them so only configured suffixes are treated as virtual.
    Returns (base, None) if the name has no recognized effort suffix.
    """
    recognized = REASONING_EFFORTS if efforts is None else tuple(efforts)
    if ":" in model_name:
        base, _, suffix = model_name.rpartition(":")
        if suffix in recognized:
            return base, suffix
    return model_name, None


def effective_reasoning_efforts(srv: SubserverConfig) -> list[str]:
    """The reasoning-effort values to expose as virtual models.

    = user-enabled efforts ∩ model-supported efforts. If the user enabled
    efforts but the model supports none, returns [] (no virtual models).
    """
    enabled = srv.reasoning_efforts
    if not enabled:
        return []
    supported = set(srv.supported_reasoning_efforts)
    if not supported:
        return []
    return [e for e in enabled if e in supported]


def init_registry(config: AppConfig) -> None:
    global _registry
    _registry = {srv.name: srv for srv in config.subservers}


def rebuild_registry() -> None:
    """Rebuild the gateway registry from every known server source.

    Merges (unified config wins on name conflicts):
    - managed_servers from config.yaml → routed via 127.0.0.1:<port>
    - remote_servers from config.yaml
    - legacy subservers from app/ollama/config.yaml

    Probed metadata from the previous registry is carried over by URL so a
    config edit doesn't force a re-probe of running servers.
    """
    global _registry
    from ..unified_config import load_unified_config
    from .config import load_config as load_ollama_config

    merged: dict[str, SubserverConfig] = {}

    ucfg = load_unified_config()
    for s in ucfg.managed_servers:
        merged[s.name] = SubserverConfig(
            name=s.name,
            url=f"http://127.0.0.1:{s.port}",
            context_length=s.context_window or 4096,
            parallel=s.parallel or 1,
            reasoning_efforts=s.reasoning_efforts,
        )
    for s in ucfg.remote_servers:
        merged.setdefault(
            s.name,
            SubserverConfig(
                name=s.name,
                url=s.url,
                family=s.family,
                context_length=s.context_length,
            ),
        )

    try:
        ocfg = load_ollama_config()
        for srv in ocfg.subservers:
            merged.setdefault(srv.name, srv)
    except Exception:
        pass

    # Carry over probed metadata by URL
    old_by_url = {old.url.rstrip("/"): old for old in _registry.values()}
    for srv in merged.values():
        old = old_by_url.get(srv.url.rstrip("/"))
        if old is not None and old.reachable:
            srv.reachable = True
            srv.upstream_model_id = old.upstream_model_id
            srv.upstream_meta = old.upstream_meta
            srv.vision = old.vision
            srv.supported_reasoning_efforts = old.supported_reasoning_efforts
            srv.size = srv.size or old.size
            if srv.parameter_size == "unknown":
                srv.parameter_size = old.parameter_size
            if srv.family == "unknown":
                srv.family = old.family

    _registry = merged


def get_subserver(model_name: str) -> SubserverConfig:
    # Resolve virtual reasoning-effort models (e.g. "name:high") to the base server.
    base, _ = split_virtual_model(model_name)
    # First try the configured name, then fall back to the probed upstream model id.
    srv = _registry.get(base)
    if srv is None:
        srv = next((s for s in _registry.values() if s.upstream_model_id == base), None)
    if srv is None:
        raise HTTPException(status_code=404, detail={"error": "model not found"})
    return srv


def get_all_subservers() -> list[SubserverConfig]:
    return list(_registry.values())
