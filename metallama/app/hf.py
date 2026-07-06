"""Hugging Face Hub client — search, list, and download GGUF models."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

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
            "oid": entry.get("oid"),  # Git blob SHA for post-download verification
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
#
# HF's CDN throttles per connection (~10 MB/s), so files are downloaded as
# fixed-size blocks fetched over several parallel range requests (same idea
# as hf_transfer/aria2). Completed blocks are tracked in a .partial.meta
# sidecar so cancelled downloads resume without refetching.

_DL_CONNECTIONS = max(1, int(os.getenv("METALLAMA_DL_CONNECTIONS", "6")))
_DL_BLOCK_SIZE = 32 * 1024 * 1024  # 32MB


def _load_block_meta(meta_path: Path, total: int) -> set[int]:
    try:
        raw = json.loads(meta_path.read_text())
        if raw.get("block_size") == _DL_BLOCK_SIZE and raw.get("total") == total:
            return {int(i) for i in raw.get("done", [])}
    except (OSError, ValueError):
        pass
    return set()


def _save_block_meta(
    meta_path: Path, total: int, done: set[int], source: dict[str, str] | None = None
) -> None:
    try:
        payload: dict = {"block_size": _DL_BLOCK_SIZE, "total": total, "done": sorted(done)}
        if source:
            payload.update(source)
        meta_path.write_text(json.dumps(payload))
    except OSError:
        pass


async def _probe(client: httpx.AsyncClient, url: str) -> tuple[int, bool]:
    """Return (total_size, supports_range) for *url*."""
    resp = await client.get(url, headers={"Range": "bytes=0-0"})
    if resp.status_code == 206:
        content_range = resp.headers.get("content-range", "")  # "bytes 0-0/12345"
        total = int(content_range.rsplit("/", 1)[-1]) if "/" in content_range else 0
        return total, total > 0
    if resp.status_code == 200:
        return int(resp.headers.get("content-length", 0)), False
    raise RuntimeError(f"HTTP {resp.status_code}")


async def _single_stream(
    client: httpx.AsyncClient,
    url: str,
    filename: str,
    partial_path: Path,
    final_path: Path,
):
    """Fallback sequential download (server without range support)."""
    async with client.stream("GET", url) as resp:
        if resp.status_code != 200:
            yield {"status": "error", "filename": filename, "error": f"HTTP {resp.status_code}"}
            return
        total = int(resp.headers.get("content-length", 0))
        completed = 0
        yield {"status": "downloading", "filename": filename, "total": total, "completed": 0}
        last_progress = 0.0
        with open(partial_path, "wb") as f:
            async for chunk in resp.aiter_bytes(chunk_size=1 << 20):
                f.write(chunk)
                completed += len(chunk)
                now = time.monotonic()
                if now - last_progress >= 0.5:
                    last_progress = now
                    yield {"status": "downloading", "filename": filename, "total": total, "completed": completed}

    partial_path.rename(final_path)
    yield {"status": "done", "filename": filename, "path": str(final_path), "size": final_path.stat().st_size}


async def _parallel_stream(
    client: httpx.AsyncClient,
    url: str,
    filename: str,
    partial_path: Path,
    meta_path: Path,
    final_path: Path,
    total: int,
    source: dict[str, str] | None = None,
):
    """Download *url* as parallel 32MB range requests into a preallocated file."""
    from collections import deque

    n_blocks = (total + _DL_BLOCK_SIZE - 1) // _DL_BLOCK_SIZE
    done = _load_block_meta(meta_path, total)
    if not done and partial_path.exists() and not meta_path.exists():
        # Contiguous partial left by the old sequential downloader: fully
        # downloaded blocks can be kept. A partial already at full size
        # without meta is ambiguous (sparse?) — redownload it.
        size = partial_path.stat().st_size
        if size < total:
            done = {i for i in range(n_blocks) if (i + 1) * _DL_BLOCK_SIZE <= size}
    done = {i for i in done if i < n_blocks}

    def block_len(idx: int) -> int:
        return min(total, (idx + 1) * _DL_BLOCK_SIZE) - idx * _DL_BLOCK_SIZE

    pending = deque(i for i in range(n_blocks) if i not in done)
    state = {"completed": sum(block_len(i) for i in done)}

    fd = os.open(partial_path, os.O_RDWR | os.O_CREAT, 0o644)
    failed_error: str | None = None
    task: asyncio.Task | None = None
    try:
        os.ftruncate(fd, total)

        async def worker() -> None:
            while True:
                try:
                    idx = pending.popleft()
                except IndexError:
                    return
                start = idx * _DL_BLOCK_SIZE
                end = min(total, start + _DL_BLOCK_SIZE) - 1
                for attempt in (1, 2):
                    got = 0
                    try:
                        async with client.stream(
                            "GET", url, headers={"Range": f"bytes={start}-{end}"}
                        ) as resp:
                            if resp.status_code != 206:
                                raise RuntimeError(f"HTTP {resp.status_code} for range request")
                            offset = start
                            async for chunk in resp.aiter_bytes(chunk_size=1 << 20):
                                os.pwrite(fd, chunk, offset)
                                offset += len(chunk)
                                got += len(chunk)
                                state["completed"] += len(chunk)
                        if got != end - start + 1:
                            raise RuntimeError(f"short read on block {idx}")
                        done.add(idx)
                        _save_block_meta(meta_path, total, done, source)
                        break
                    except asyncio.CancelledError:
                        state["completed"] -= got
                        raise
                    except Exception:
                        state["completed"] -= got
                        if attempt == 2:
                            raise

        n_workers = min(_DL_CONNECTIONS, max(1, len(pending)))
        task = asyncio.ensure_future(asyncio.gather(*(worker() for _ in range(n_workers))))

        yield {"status": "downloading", "filename": filename, "total": total, "completed": state["completed"]}
        try:
            while not task.done():
                await asyncio.sleep(0.4)
                yield {"status": "downloading", "filename": filename, "total": total, "completed": state["completed"]}
            await task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failed_error = str(exc)
    finally:
        if task is not None:
            task.cancel()
            try:
                await task  # always retrieve the (Cancelled)Error
            except BaseException:
                pass
        os.close(fd)
        if len(done) < n_blocks:
            _save_block_meta(meta_path, total, done, source)

    if failed_error:
        yield {"status": "error", "filename": filename, "error": failed_error}
        return

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

    limits = httpx.Limits(max_connections=_DL_CONNECTIONS + 2)
    try:
        async with httpx.AsyncClient(
            timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True, limits=limits
        ) as client:
            for filename in filenames:
                url = f"{_HF_RESOLVE}/{ns}/{name}/resolve/main/{quote(filename)}"
                final_path = dest / filename
                partial_path = dest / f"{filename}.partial"
                meta_path = dest / f"{filename}.partial.meta"

                total, supports_range = await _probe(client, url)
                if supports_range and total > _DL_BLOCK_SIZE:
                    stream = _parallel_stream(
                        client, url, filename, partial_path, meta_path, final_path, total,
                        source={"repo_id": repo_id, "filename": filename},
                    )
                else:
                    stream = _single_stream(client, url, filename, partial_path, final_path)

                had_error = False
                async for msg in stream:
                    if msg.get("status") == "error":
                        had_error = True
                    yield msg
                if had_error:
                    return
    except Exception as exc:
        yield {"status": "error", "error": str(exc)}
