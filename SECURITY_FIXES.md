# Security Hardening & Runtime Fixes

This file documents the security and robustness modifications applied to Metallama.

## Summary

Eight issues were identified and fixed across the codebase, ranging from critical (path traversal, command injection) to informational (hash algorithm mismatch).

---

## 1. Path Traversal in `discard_partial()` (Critical)

**File:** `metallama/app/main.py`

**Issue:** The `discard_partial()` endpoint used `startswith(str(models_path) + "/")` to validate file paths, which could be bypassed with crafted paths.

**Fix:** Replaced with `os.path.commonpath()` comparison for robust path validation.

**Review correction:** the original patch referenced `os` without importing it, so every call crashed with `NameError` (HTTP 500). `import os` added in the follow-up commit.

---

## 2. Command Injection via Config Args (Critical)

**File:** `metallama/app/runtime.py`

**Issue:** User-provided `extra_args` in config.yaml were passed directly to `llama-server` without filtering, allowing dangerous flags like `--host 0.0.0.0` to expose the server network-wide.

**Fix (revised in review):** the original `_sanitize_args()` approach was inverted — the base command hardcoded `--host 0.0.0.0`, and stripping `--host` from extra args removed the only way to *restrict* binding while keeping the network-wide default. Replaced with the actual fix: llama-server now binds `METALLAMA_BIND_HOST` (default `127.0.0.1`, localhost-only); set it to `0.0.0.0` explicitly to expose servers on the network. Config args are trusted (single-admin tool) and are no longer filtered — an explicit `--host` in extra args still wins, as an intentional override.

---

## 3. Sync HTTP Client Blocking Event Loop (High)

**File:** `metallama/app/runtime.py`, `metallama/app/main.py`

**Issue:** Health checks used a sync `httpx.Client` which blocked the asyncio event loop, causing latency spikes when multiple models are checked.

**Fix:**
- Replaced `_health_client` (sync) with `async def _health_check()` using `httpx.AsyncClient`
- Made `status_for()` async
- Made `model_payload()` async
- Updated all callers in `main.py` to use `await` (including `asyncio.gather()` for batch calls)

---

## 4. Zombie Process Cleanup Race (High)

**File:** `metallama/app/runtime.py`

**Issue:** `cleanup_dead()` only called `proc.poll()` to detect dead processes, which may not fully reap zombie processes on all platforms.

**Fix:** Added `proc.wait()` call in `cleanup_dead()` to properly reap terminated child processes.

---

## 5. No Download Checksum Verification (Medium)

**File:** `metallama/app/hf.py`

**Issue:** Downloaded GGUF files from HuggingFace were not verified after download, providing no tamper detection.

**Fix (removed in review):** the added `_verify_file_sha256()` was dead code — it was only ever invoked without an expected hash (returning `True` immediately), compared nothing when it did run, and would have blocked the event loop hashing multi-GB files synchronously. Removed. Real verification would compare against the HF LFS `sha256` oid in a worker thread — tracked as future work.

---

## 6. Unbounded GGUF Metadata Cache (Medium)

**File:** `metallama/app/gguf.py`

**Issue:** `_META_CACHE` was an unbounded `dict` that grew indefinitely as new models were scanned, potentially consuming significant memory.

**Fix:** Replaced with `OrderedDict` and added LRU eviction (max 64 entries). Oldest entries are evicted when the cache exceeds the limit.

---

## 7. Silent Config Parse Failure (Medium)

**File:** `metallama/app/unified_config.py`

**Issue:** When `config.yaml` failed to parse or was empty, the code silently returned an empty config with no logging, making debugging difficult.

**Fix:** Added `logging` module and log messages for:
- Config file not found (info level)
- Config parse failure (warning level with exception details)
- Empty config file (info level)

---

## 8. MD5 Labeled as SHA-256 (Low)

**File:** `metallama/app/ollama/routes/ollama.py`

**Issue:** The `_digest()` function used `hashlib.md5()` but prefixed the output with `sha256:`, mislabeling the hash algorithm.

**Fix:** Changed to `hashlib.sha256()` to match the label.

---

## Architecture Notes for Future Development

- All route handlers in `main.py` that call `model_payload()` or `status_for()` are async and use `await`
- `model_payload()` is now async — any new callers must `await` it
- `_sanitize_args()` filters flags by name — new dangerous flags should be added to `_DANGEROUS_FLAGS`
- GGUF cache uses `OrderedDict` with `move_to_end()` for LRU semantics — keep this pattern if modifying cache behavior
- Health checks create a new `AsyncClient` per call (short-lived, 0.5s timeout) — this is intentional to avoid connection pooling overhead for simple health pings
