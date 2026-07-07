from __future__ import annotations

from typing import Any

import httpx

from .registry import get_all_subservers
from .schemas import SubserverConfig

_PROBE_TIMEOUT = httpx.Timeout(3.0)


def _fallback_arch(current_family: str) -> str:
    if current_family and current_family != "unknown":
        return current_family
    return "llama"


def _pick_upstream_model(models: list[dict], configured_name: str) -> dict | None:
    if not models:
        return None
    for model in models:
        if model.get("id") == configured_name:
            return model
    return models[0]


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _extract_props_context_length(payload: dict[str, Any], parallel: int = 1) -> int | None:
    """Extract per-slot context length from llama-server's /props payload.

    llama-server reports n_ctx as the TOTAL context budget (ctx_size × parallel),
    not the per-slot value. We divide by parallel to recover the per-slot context.
    """
    direct = _coerce_int(payload.get("n_ctx"))
    if direct is None:
        dgs = payload.get("default_generation_settings")
        if isinstance(dgs, dict):
            direct = _coerce_int(dgs.get("n_ctx"))
    if direct is None:
        return None
    # If the payload reports n_parallel, prefer it (handles remote servers
    # where we don't know the configured parallel count).
    n_parallel = _coerce_int(payload.get("n_parallel")) or parallel
    if n_parallel > 1 and direct % n_parallel == 0:
        return direct // n_parallel
    return direct


_DEFAULT_CONTEXT_LENGTH = 4096


async def probe_one(srv: SubserverConfig, client: httpx.AsyncClient) -> None:
    """Probe a single subserver and backfill its metadata in place."""
    srv.family = _fallback_arch(srv.family)
    props_ctx: int | None = None
    srv.reachable = False

    try:
        r_props = await client.get(f"{srv.url}/props")
        if r_props.status_code == 200:
            srv.reachable = True
            props_payload = r_props.json()
            if isinstance(props_payload, dict):
                props_ctx = _extract_props_context_length(props_payload, srv.parallel)
    except (httpx.ConnectError, httpx.TimeoutException, ValueError):
        pass

    try:
        r_models = await client.get(f"{srv.url}/v1/models")
        if r_models.status_code == 200:
            srv.reachable = True
            models = r_models.json().get("data", [])
            selected = _pick_upstream_model(models, srv.name)
            if selected:
                meta = selected.get("meta", {}) or {}
                srv.upstream_model_id = selected.get("id", srv.name)
                srv.upstream_meta = meta

                if srv.size == 0:
                    size = _coerce_int(selected.get("size")) or _coerce_int(meta.get("size"))
                    if size is not None:
                        srv.size = size

                if srv.parameter_size == "unknown":
                    n_params = _coerce_int(meta.get("n_params"))
                    if n_params is not None:
                        srv.parameter_size = f"{round(n_params / 1e9, 1)}B"

                # Only update context_length if it wasn't explicitly set in config
                if srv.context_length == _DEFAULT_CONTEXT_LENGTH:
                    ctx = (
                        props_ctx
                        or _coerce_int(meta.get("n_ctx"))
                        or _coerce_int(meta.get("context_length"))
                        or _coerce_int(meta.get("n_ctx_train"))
                    )
                    if ctx is not None:
                        srv.context_length = ctx

                srv.family = meta.get("general.architecture", srv.family)

    except (httpx.ConnectError, httpx.TimeoutException):
        pass


async def probe_subservers() -> None:
    """Query all subservers and backfill missing metadata."""
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
        for srv in get_all_subservers():
            await probe_one(srv, client)
