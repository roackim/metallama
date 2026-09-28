from __future__ import annotations

from fastapi import HTTPException

from .schemas import AppConfig, SubserverConfig

_registry: dict[str, SubserverConfig] = {}

# Every reasoning-effort value the gateway understands, by increasing effort.
# "none" disables thinking (llama-server maps it to enable_thinking=false).
REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh")


def split_virtual_model(model_name: str) -> tuple[str, str | None]:
    """Split a model name into (base_name, effort_suffix).

    A client that can't send an effort parameter (e.g. VS Code's Ollama
    integration) can select "Qwen3.8-27B:low" instead. Returns (base, None)
    if the name has no recognized effort suffix.
    """
    base, sep, suffix = model_name.rpartition(":")
    if sep and suffix in REASONING_EFFORTS:
        return base, suffix
    return model_name, None


def effective_reasoning_efforts(srv: SubserverConfig) -> list[str]:
    """The reasoning-effort values a request may use on this server.

    = user-allowed efforts ∩ model-supported efforts. Empty means the gateway
    doesn't police efforts for this server (requests pass through as-is).
    """
    allowed = set(srv.reasoning_efforts) & set(srv.supported_reasoning_efforts)
    return [e for e in REASONING_EFFORTS if e in allowed]


def virtual_efforts(srv: SubserverConfig) -> list[str]:
    """Efforts exposed as virtual "name:effort" models ([] when not virtualized)."""
    return effective_reasoning_efforts(srv) if srv.virtualize_efforts else []


def resolve_reasoning_effort(srv: SubserverConfig, model_name: str, body: dict) -> str | None:
    """The reasoning effort a request asks for, or None for the model default.

    Sources, highest priority first (explicit request fields beat the model
    suffix, which exists only for clients that can't send a parameter):
    - Ollama `think`: false → "none", a level string → that level
      (true only means "thinking on", so the suffix or default still applies)
    - OpenAI `reasoning_effort` (also accepted inside Ollama `options`)
    - OpenAI Responses / OpenRouter `reasoning.effort`
    - the virtual model suffix ("name:low")

    Raises 400 when the server has allowed efforts configured and the
    requested one isn't among them.
    """
    effort: str | None = None
    think = body.get("think")
    options = body.get("options") if isinstance(body.get("options"), dict) else {}
    reasoning = body.get("reasoning") if isinstance(body.get("reasoning"), dict) else {}
    if think is False:
        effort = "none"
    elif isinstance(think, str):
        effort = think
    elif body.get("reasoning_effort") is not None:
        effort = str(body["reasoning_effort"])
    elif options.get("reasoning_effort") is not None:
        effort = str(options["reasoning_effort"])
    elif reasoning.get("effort") is not None:
        effort = str(reasoning["effort"])
    else:
        effort = split_virtual_model(model_name)[1]
    if effort is None:
        return None
    effort = effort.strip().lower()

    allowed = effective_reasoning_efforts(srv)
    if allowed and effort not in allowed:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"reasoning effort '{effort}' is not allowed for model '{srv.name}'",
                "allowed_efforts": allowed,
            },
        )
    return effort


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
    from .probe import _infer_default_effort, _infer_reasoning_efforts, server_chat_template

    merged: dict[str, SubserverConfig] = {}

    ucfg = load_unified_config()
    for s in ucfg.managed_servers:
        merged[s.name] = SubserverConfig(
            name=s.name,
            url=f"http://127.0.0.1:{s.port}",
            context_length=s.context_window or 4096,
            parallel=s.parallel or 1,
            reasoning_efforts=s.reasoning_efforts,
            virtualize_efforts=s.virtualize_efforts,
        )
        # Known before the server starts; replaced by /props when probed.
        template = server_chat_template(s.model_path, s.extra_args)
        merged[s.name].supported_reasoning_efforts = _infer_reasoning_efforts(template)
        merged[s.name].default_reasoning_effort = _infer_default_effort(template)
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
            srv.default_reasoning_effort = old.default_reasoning_effort
            srv.size = srv.size or old.size
            if srv.parameter_size == "unknown":
                srv.parameter_size = old.parameter_size
            if srv.family == "unknown":
                srv.family = old.family

    _registry = merged


def get_subserver(model_name: str) -> SubserverConfig:
    # Resolve virtual reasoning-effort models (e.g. "name:high") to the base server.
    base, effort = split_virtual_model(model_name)
    # First try the configured name, then fall back to the probed upstream model id.
    srv = _registry.get(base)
    if srv is None:
        srv = next((s for s in _registry.values() if s.upstream_model_id == base), None)
    # A virtual model only exists while the server virtualizes that effort.
    if srv is None or (effort is not None and effort not in virtual_efforts(srv)):
        raise HTTPException(status_code=404, detail={"error": "model not found"})
    return srv


def get_all_subservers() -> list[SubserverConfig]:
    return list(_registry.values())
