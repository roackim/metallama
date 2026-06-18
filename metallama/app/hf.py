"""Hugging Face Hub client — search, list, and download GGUF models."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .config import Config

_HF_API = "https://huggingface.co/api"
_HF_RESOLVE = "https://huggingface.co"
_TIMEOUT = httpx.Timeout(30.0)
_DOWNLOAD_TIMEOUT = httpx.Timeout(600.0, connect=30.0)

# Quant suffixes commonly found in GGUF filenames
_QUANT_RE = re.compile(
    r"(IQ[1-4][S]?_[A-Z]+|Q[2-8]_[A-Z]+|Q[4-8]_[0-9]|F16|BF16|F32)",
    re.IGNORECASE,
)
_SHARD_RE = re.compile(r"-(\d+)-of-(\d+)\.gguf$", re.IGNORECASE)


def _parse_quant(filename: str) -> str | None:
    m = _QUANT_RE.search(filename)
    return m.group(0).upper() if m else None


def _parse_shard(filename: str) -> tuple[int, int] | None:
    m = _SHARD_RE.search(filename)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ── Search ─────────────────────────────────────────────────────────────────


async def search_models(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search HF Hub for GGUF repos matching *query*."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(
            f"{_HF_API}/models",
            params={
                "search": query,
                "filter": "gguf",
                "sort": "downloads",
                "direction": "-1",
                "limit": limit,
            },
        )
        r.raise_for_status()
        results = r.json()
    return [
        {
            "id": item.get("id", ""),
            "downloads": item.get("downloads", 0),
            "likes": item.get("likes", 0),
            "pipeline_tag": item.get("pipeline_tag", ""),
            "last_modified": item.get("lastModified", ""),
        }
        for item in results
    ]


# ── List files ─────────────────────────────────────────────────────────────


async def list_gguf_files(repo_id: str) -> list[dict[str, Any]]:
    """List .gguf files in a HF repo (main branch), with parsed metadata."""
    ns, name = _split_repo(repo_id)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(
            f"{_HF_API}/models/{ns}/{name}/tree/main",
            params={"recursive": "true"},
        )
        r.raise_for_status()
        entries = r.json()

    files: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("type") != "file":
            continue
        path = entry.get("path", "")
        if not path.endswith(".gguf"):
            continue
        files.append({
            "path": path,
            "filename": Path(path).name,
            "size": entry.get("size", 0),
            "size_human": _human_size(entry.get("size", 0)),
            "quant": _parse_quant(path),
            "shard": _parse_shard(path),
        })

    # Group shards: if any file is a shard, collect shard groups
    shard_groups: dict[str, list[dict]] = {}
    singles: list[dict] = []
    for f in files:
        if f["shard"]:
            group_key = _SHARD_RE.sub("", f["filename"])
            shard_groups.setdefault(group_key, []).append(f)
        else:
            singles.append(f)

    # Flatten back: shards first (grouped), then singles
    result: list[dict[str, Any]] = []
    for group_key, shards in sorted(shard_groups.items()):
        shards.sort(key=lambda s: s["shard"][0])
        total_size = sum(s["size"] for s in shards)
        result.append({
            "type": "sharded",
            "base_name": group_key,
            "quant": shards[0].get("quant"),
            "shards": shards,
            "shard_count": len(shards),
            "size": total_size,
            "size_human": _human_size(total_size),
        })
    for f in singles:
        f["type"] = "single"
        result.append(f)

    return result


def _split_repo(repo_id: str) -> tuple[str, str]:
    parts = repo_id.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid repo id: {repo_id!r} (expected namespace/name)")
    return parts[0], parts[1]


# ── Download ───────────────────────────────────────────────────────────────


async def download_model(
    repo_id: str,
    filenames: list[str],
    dest_dir: str | None = None,
):
    """Yield NDJSON progress lines while downloading *filenames* from *repo_id*.

    Files are written to a .partial temp file and renamed on completion.
    For sharded models, all files go into a subfolder named after the repo.
    Yields dicts: status, total, completed, filename, done, error, path.
    """
    ns, name = _split_repo(repo_id)
    models_dir = Path(dest_dir or Config.MODELS_DIR)
    if not models_dir:
        yield {"status": "error", "error": "METALLAMA_MODELS_DIR is not set"}
        return

    # Sharded models go into a subfolder; singles go directly into models_dir
    is_sharded = len(filenames) > 1
    if is_sharded:
        dest = models_dir / name
    else:
        dest = models_dir
    dest.mkdir(parents=True, exist_ok=True)

    for filename in filenames:
        url = f"{_HF_RESOLVE}/{ns}/{name}/resolve/main/{quote(filename)}"
        final_path = dest / filename
        partial_path = dest / f"{filename}.partial"

        # Resume: start from existing partial size
        existing_size = partial_path.stat().st_size if partial_path.exists() else 0

        headers: dict[str, str] = {}
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"

        try:
            async with httpx.AsyncClient(
                timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True
            ) as client:
                async with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code not in (200, 206):
                        yield {
                            "status": "error",
                            "filename": filename,
                            "error": f"HTTP {resp.status_code}",
                        }
                        continue

                    # Total size
                    content_length = int(resp.headers.get("content-length", 0))
                    if resp.status_code == 206:
                        total = existing_size + content_length
                    else:
                        total = content_length
                        existing_size = 0  # server doesn't support range

                    completed = existing_size
                    yield {
                        "status": "downloading",
                        "filename": filename,
                        "total": total,
                        "completed": completed,
                    }

                    mode = "ab" if resp.status_code == 206 else "wb"
                    with open(partial_path, mode) as f:
                        async for chunk in resp.aiter_bytes(chunk_size=1 << 18):  # 256KB
                            f.write(chunk)
                            completed += len(chunk)
                            yield {
                                "status": "downloading",
                                "filename": filename,
                                "total": total,
                                "completed": completed,
                            }

            # Rename partial → final
            partial_path.rename(final_path)
            yield {
                "status": "done",
                "filename": filename,
                "path": str(final_path),
                "size": final_path.stat().st_size,
            }

        except Exception as exc:
            yield {"status": "error", "filename": filename, "error": str(exc)}
            return
