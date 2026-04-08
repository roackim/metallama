from __future__ import annotations

import asyncio
import io
import json
import re
from pathlib import Path
from urllib.parse import quote, unquote
import urllib.error
import urllib.request
import uuid
import zipfile
from typing import Any

from fastapi import HTTPException

from .profiles import MODEL_PROFILES
from .runtime import status_for

_zip_store: dict[str, tuple[bytes, str]] = {}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def extract_first_markdown(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()

    if isinstance(payload, list):
        for item in payload:
            text = extract_first_markdown(item)
            if text:
                return text
        return ""

    if isinstance(payload, dict):
        preferred_keys = (
            "md_content",
            "markdown",
            "md",
            "content",
            "text",
        )
        for key in preferred_keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for key in ("result", "results", "data", "output", "outputs", "files", "pages"):
            if key in payload:
                text = extract_first_markdown(payload[key])
                if text:
                    return text

        for value in payload.values():
            text = extract_first_markdown(value)
            if text:
                return text

    return ""


def _get_mineru_profile():
    profile = MODEL_PROFILES.get("mineru-ocr")
    if not profile:
        raise HTTPException(status_code=500, detail="MinerU model profile is not configured")
    if status_for(profile) != "running":
        raise HTTPException(status_code=409, detail="OCR server is not running. Start MinerU first.")
    return profile


def _build_multipart_body(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    form_fields: dict[str, str],
) -> tuple[str, bytes]:
    boundary = f"----metallama-ocr-{uuid.uuid4().hex}"
    body = bytearray()

    for key, value in form_fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{value}\r\n".encode("utf-8"))

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'.encode("utf-8"))
    body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    return boundary, bytes(body)


async def request_mineru_markdown(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    parse_method: str,
    backend: str,
) -> str:
    profile = _get_mineru_profile()
    request_filename = f"{uuid.uuid4().hex}_{filename}"

    form_fields = {
        "return_md": "true",
        "parse_method": parse_method or "auto",
        "backend": backend,
    }
    boundary, body = _build_multipart_body(file_bytes, request_filename, content_type, form_fields)

    def _send_request() -> tuple[int, str, str]:
        request = urllib.request.Request(
            url=f"http://127.0.0.1:{profile.port}/file_parse",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                status = response.status
                response_type = response.headers.get("Content-Type", "")
                payload = response.read().decode("utf-8", errors="ignore")
                return status, response_type, payload
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore")
            raise HTTPException(
                status_code=502,
                detail=f"MinerU parse failed ({exc.code}): {payload[:400]}",
            ) from exc
        except urllib.error.URLError as exc:
            raise HTTPException(status_code=502, detail=f"Cannot reach OCR server: {exc}") from exc

    status, response_type, payload = await asyncio.to_thread(_send_request)
    if status >= 400:
        raise HTTPException(status_code=502, detail=f"MinerU parse failed ({status})")

    parsed_payload: Any = payload
    if "json" in response_type:
        try:
            parsed_payload = json.loads(payload)
        except json.JSONDecodeError:
            parsed_payload = payload

    markdown = extract_first_markdown(parsed_payload)
    if not markdown:
        raise HTTPException(status_code=502, detail="MinerU returned no markdown content")

    return markdown


async def request_mineru_zip(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    parse_method: str,
    backend: str,
) -> tuple[str, str, int]:
    profile = _get_mineru_profile()
    request_filename = f"{uuid.uuid4().hex}_{filename}"

    form_fields = {
        "return_md": "true",
        "return_images": "true",
        "response_format_zip": "true",
        "parse_method": parse_method or "auto",
        "backend": backend,
    }
    boundary, body = _build_multipart_body(file_bytes, request_filename, content_type, form_fields)

    def _send_request() -> tuple[int, str, bytes]:
        request = urllib.request.Request(
            url=f"http://127.0.0.1:{profile.port}/file_parse",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                status = response.status
                resp_type = response.headers.get("Content-Type", "")
                raw = response.read()
                return status, resp_type, raw
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore")
            raise HTTPException(
                status_code=502,
                detail=f"MinerU parse failed ({exc.code}): {payload[:400]}",
            ) from exc
        except urllib.error.URLError as exc:
            raise HTTPException(status_code=502, detail=f"Cannot reach OCR server: {exc}") from exc

    status, resp_type, raw = await asyncio.to_thread(_send_request)
    if status >= 400:
        raise HTTPException(status_code=502, detail=f"MinerU parse failed ({status})")

    if not raw:
        raise HTTPException(status_code=502, detail="MinerU returned empty response")

    raw, image_count, markdown = _normalize_zip_layout(raw, Path(filename).stem)

    if not markdown:
        markdown = "(Images extracted — no markdown found in ZIP)"

    stem = Path(filename).stem
    zip_id = uuid.uuid4().hex
    _zip_store[zip_id] = (raw, f"{stem}.ocr.zip")

    return markdown, zip_id, image_count


def get_zip(zip_id: str) -> tuple[bytes, str] | None:
    return _zip_store.get(zip_id)


def _normalize_zip_layout(raw_zip: bytes, document_stem: str) -> tuple[bytes, int, str]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as source_zip:
            members: list[tuple[str, bytes]] = [
                (info.filename, source_zip.read(info.filename))
                for info in source_zip.infolist()
                if not info.is_dir()
            ]
    except zipfile.BadZipFile:
        return raw_zip, 0, ""

    markdown_entries = [(n.replace("\\", "/"), b) for n, b in members if n.lower().endswith(".md")]
    if not markdown_entries:
        return raw_zip, 0, ""

    markdown_text = ""
    for _, payload in markdown_entries:
        candidate = payload.decode("utf-8", errors="ignore").strip()
        if candidate:
            markdown_text = candidate
            break

    if not markdown_text:
        return raw_zip, 0, ""

    image_entries: dict[str, bytes] = {}
    image_by_base: dict[str, list[str]] = {}
    for name, payload in members:
        normalized = name.replace("\\", "/")
        ext = Path(normalized).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        image_entries[normalized] = payload
        base = Path(normalized).name
        image_by_base.setdefault(base, []).append(normalized)

    ordered_matches = _find_markdown_image_matches(markdown_text, image_entries, image_by_base)

    image_map: dict[str, str] = {}
    for index, old_path in enumerate(ordered_matches, start=1):
        ext = Path(old_path).suffix.lower()
        image_map[old_path] = f"images/img_{index:04d}{ext}"

    normalized_markdown = _rewrite_markdown_image_refs(markdown_text, image_map)

    safe_stem = Path(document_stem).name or "document"
    updated_buffer = io.BytesIO()
    with zipfile.ZipFile(updated_buffer, "w", compression=zipfile.ZIP_DEFLATED) as out_zip:
        out_zip.writestr(f"{safe_stem}.md", normalized_markdown.encode("utf-8"))
        for old_path in ordered_matches:
            out_zip.writestr(image_map[old_path], image_entries[old_path])

    return updated_buffer.getvalue(), len(ordered_matches), normalized_markdown


def _find_markdown_image_matches(
    markdown_text: str,
    image_entries: dict[str, bytes],
    image_by_base: dict[str, list[str]],
) -> list[str]:
    ordered_refs: list[str] = []

    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", markdown_text):
        raw = match.group(1).strip().strip("<>").split()[0]
        if raw:
            ordered_refs.append(raw)

    for match in re.finditer(r"<img[^>]+src=[\"']([^\"']+)[\"']", markdown_text, flags=re.IGNORECASE):
        raw = match.group(1).strip()
        if raw:
            ordered_refs.append(raw)

    ordered_matches: list[str] = []
    seen: set[str] = set()
    for ref in ordered_refs:
        resolved = _resolve_image_ref(ref, image_entries, image_by_base)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        ordered_matches.append(resolved)

    return ordered_matches


def _resolve_image_ref(
    ref: str,
    image_entries: dict[str, bytes],
    image_by_base: dict[str, list[str]],
) -> str | None:
    cleaned = ref.split("?")[0].split("#")[0]
    candidates = {
        cleaned,
        cleaned.lstrip("./"),
        unquote(cleaned),
        unquote(cleaned).lstrip("./"),
    }

    for candidate in list(candidates):
        candidates.add(candidate.replace("\\", "/"))

    for candidate in candidates:
        if candidate in image_entries:
            return candidate

    for candidate in candidates:
        base = Path(candidate).name
        hits = image_by_base.get(base, [])
        if len(hits) == 1:
            return hits[0]

    return None


def _rewrite_markdown_image_refs(markdown_text: str, image_map: dict[str, str]) -> str:
    updated = markdown_text
    replacement_items = sorted(image_map.items(), key=lambda item: len(item[0]), reverse=True)

    for old_path, new_path in replacement_items:
        old_base = Path(old_path).name
        new_base = Path(new_path).name

        updated = updated.replace(old_path, new_path)
        updated = updated.replace(quote(old_path), quote(new_path))

        updated = updated.replace(old_base, new_base)
        updated = updated.replace(quote(old_base), quote(new_base))

    return updated
