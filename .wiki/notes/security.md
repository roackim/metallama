# Security

## Auth Model

Admin auth is optional and disabled by default. It is enabled by setting
`METALLAMA_ADMIN_PASS_HASH` to a scrypt hash string.

- **Password hashing**: `hashlib.scrypt` (no external deps). The hash is a
  self-contained string `scrypt$N$r$p$<salt_b64>$<key_b64>` produced by
  `auth.hash_password()`. `hash_password.py` is a CLI helper to generate it.
- **Sessions**: on successful login, an in-memory session token is created with an
  8-hour TTL (`_SESSION_TTL`). Tokens are stored in a module-level dict and validated
  with constant-time comparison via `hmac.compare_digest`.
- **Guard**: the `admin_guard` FastAPI dependency protects mutating routes. When auth
  is disabled, all requests pass through. When enabled, requests must carry a valid
  `Authorization: Bearer <token>` header.
- **Frontend**: the token is stored in `sessionStorage` (`metallama_admin_token`) and
  attached to requests by `core/auth.js`.

## Trust Boundaries

- **Config args are trusted**: `extra_args` in config.yaml are passed directly to
  `llama-server`. This is a single-admin tool, so args are not filtered. An explicit
  `--host` in extra args intentionally overrides the bind host.
- **Bind host**: `METALLAMA_BIND_HOST` controls where llama-servers bind. Set to
  `127.0.0.1` to restrict to localhost only (default is `0.0.0.0`).

## Path Traversal Protection

File-deletion endpoints (`/api/library/partials/discard`, `/api/library/models/delete`)
validate that the resolved target path stays within the models directory using
`os.path.commonpath()` comparison, and that the file suffix is `.partial` / `.gguf`
respectively. See `SECURITY_FIXES.md` for the history of these fixes.

## Secrets Handling

- `.env` is gitignored and holds `METALLAMA_ADMIN_PASS_HASH` and other secrets.
- Session tokens are never logged.
- The OpenAI gateway accepts any non-empty API key (it is a local passthrough, not a
  real auth boundary).

## Documented Fixes

See `SECURITY_FIXES.md` at the repo root for a detailed record of security hardening
and runtime fixes (path traversal, command injection, sync-client event-loop blocking,
etc.).

## See Also
- [Architecture](architecture.md)
- [Config](config.md)
- [app tree](../tree/app.md)