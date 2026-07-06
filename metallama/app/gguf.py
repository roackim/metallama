from __future__ import annotations

import struct
from collections import OrderedDict
from pathlib import Path
from typing import Any, BinaryIO

# GGUF value types
_U8, _I8, _U16, _I16, _U32, _I32, _F32, _BOOL, _STRING, _ARRAY, _U64, _I64, _F64 = range(13)

_SCALAR_FMT = {
    _U8: "<B", _I8: "<b", _U16: "<H", _I16: "<h",
    _U32: "<I", _I32: "<i", _F32: "<f", _BOOL: "<?",
    _U64: "<Q", _I64: "<q", _F64: "<d",
}


def _read_scalar(f: BinaryIO, vtype: int) -> Any:
    fmt = _SCALAR_FMT[vtype]
    return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]


def _read_len(f: BinaryIO) -> int:
    return struct.unpack("<Q", f.read(8))[0]


def _skip_value(f: BinaryIO, vtype: int) -> None:
    if vtype in _SCALAR_FMT:
        f.seek(struct.calcsize(_SCALAR_FMT[vtype]), 1)
    elif vtype == _STRING:
        f.seek(_read_len(f), 1)
    elif vtype == _ARRAY:
        elem_type = struct.unpack("<I", f.read(4))[0]
        count = _read_len(f)
        if elem_type in _SCALAR_FMT:
            f.seek(count * struct.calcsize(_SCALAR_FMT[elem_type]), 1)
        else:
            for _ in range(count):
                _skip_value(f, elem_type)
    else:
        raise ValueError(f"Unknown GGUF value type {vtype}")


# (path, mtime, size) -> metadata dict (bounded LRU cache)
_META_CACHE: OrderedDict[tuple[str, float, int], dict[str, Any] | None] = OrderedDict()
_MAX_CACHE_SIZE = 64  # Prevent unbounded memory growth


def read_metadata(path: str | Path) -> dict[str, Any] | None:
    """Read scalar/string metadata KVs from a GGUF file header.

    Skips tokenizer.* keys and array values (not needed for sizing).
    Returns None if the file is not a parseable GGUF.
    """
    p = Path(path)
    try:
        stat = p.stat()
    except OSError:
        return None
    cache_key = (str(p), stat.st_mtime, stat.st_size)
    if cache_key in _META_CACHE:
        # Move to end (most recently used)
        _META_CACHE.move_to_end(cache_key)
        return _META_CACHE[cache_key]

    meta: dict[str, Any] | None = {}
    try:
        with p.open("rb") as f:
            if f.read(4) != b"GGUF":
                raise ValueError("not a GGUF file")
            version = struct.unpack("<I", f.read(4))[0]
            if version < 2:
                raise ValueError(f"unsupported GGUF version {version}")
            f.seek(8, 1)  # tensor_count
            kv_count = _read_len(f)
            for _ in range(kv_count):
                key = f.read(_read_len(f)).decode("utf-8", errors="replace")
                vtype = struct.unpack("<I", f.read(4))[0]
                if vtype in _SCALAR_FMT and not key.startswith("tokenizer."):
                    meta[key] = _read_scalar(f, vtype)
                elif vtype == _STRING and not key.startswith("tokenizer."):
                    meta[key] = f.read(_read_len(f)).decode("utf-8", errors="replace")
                else:
                    _skip_value(f, vtype)
    except (OSError, ValueError, struct.error):
        meta = None

    # Evict oldest entries if cache exceeds max size
    while len(_META_CACHE) >= _MAX_CACHE_SIZE:
        _META_CACHE.popitem(last=False)

    _META_CACHE[cache_key] = meta
    return meta


def estimate_vram_gb(
    model_path: str | Path,
    context_tokens: int,
    draft_model_path: str | Path | None = None,
    kv_bytes_per_element: float = 2.0,
) -> dict[str, float] | None:
    """Rough VRAM estimate (upper bound) for fully offloaded weights + KV cache.

    Returns {"weights_gb", "kv_cache_gb", "total_gb"} or None if the model
    file can't be read. kv_bytes_per_element: 2.0 for f16, ~1.06 for q8_0.
    Models with sliding-window/hybrid attention need less than estimated.
    """
    p = Path(model_path)
    try:
        weights_bytes = p.stat().st_size
    except OSError:
        return None
    if draft_model_path:
        try:
            weights_bytes += Path(draft_model_path).stat().st_size
        except OSError:
            pass

    kv_bytes = 0.0
    meta = read_metadata(p)
    if meta:
        arch = meta.get("general.architecture", "")
        layers = meta.get(f"{arch}.block_count")
        heads = meta.get(f"{arch}.attention.head_count")
        kv_heads = meta.get(f"{arch}.attention.head_count_kv") or heads
        embed = meta.get(f"{arch}.embedding_length")
        key_len = meta.get(f"{arch}.attention.key_length")
        if not key_len and embed and heads:
            key_len = embed // heads
        value_len = meta.get(f"{arch}.attention.value_length") or key_len
        if layers and kv_heads and key_len and value_len:
            # Hybrid SSM/attention models (e.g. Qwen3.5+) only keep a KV cache
            # on every Nth layer; the rest use constant-size recurrent state.
            interval = meta.get(f"{arch}.full_attention_interval")
            kv_layers = max(1, int(layers) // int(interval)) if interval and int(interval) > 1 else int(layers)
            kv_bytes = float(kv_layers) * context_tokens * kv_heads * (key_len + value_len) * kv_bytes_per_element

    overhead_bytes = 1.0 * 1024**3  # compute buffers, graph, fragmentation
    total = weights_bytes + kv_bytes + overhead_bytes
    return {
        "weights_gb": round(weights_bytes / 1024**3, 1),
        "kv_cache_gb": round(kv_bytes / 1024**3, 1),
        "total_gb": round(total / 1024**3, 1),
    }
