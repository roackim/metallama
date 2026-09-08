# metallama/app/static/js/core

Shared frontend utilities used across feature modules.

## Files

| File | Purpose |
|------|---------|
| `api.js` | HTTP client: `api(path, options)` — wraps `fetch()` with JSON handling and auth headers |
| `auth.js` | Admin auth: login/logout, token storage, session verification, admin state callbacks |
| `clipboard.js` | Copy-to-clipboard utility |
| `download.js` | Trigger browser download from blob/URL |
| `uiMessage.js` | Set/clear the global UI status message banner |

## Key Functions

| Name | File | What it does |
|------|------|-------------|
| `api()` | api.js | Fetch with JSON handling and auto-attached `Authorization` header |
| `login()` | auth.js | POST password to `/api/auth/login`, stores token in `sessionStorage` |
| `logout()` | auth.js | Revoke session on server, clear token from `sessionStorage` |
| `verifyToken()` | auth.js | Validate stored token against `/api/auth/verify`, clears if invalid |
| `isAdmin()` | auth.js | Returns `true` if auth disabled or a valid token is stored |
| `checkAuthEnabled()` | auth.js | Fetches `/api/auth/status`, caches result |
| `onAdminChange()` | auth.js | Subscribe to admin state changes (login/logout) |
| `setConfigMessage()` | uiMessage.js | Shows a status message in `#ui-message` element |
| `copyToClipboard()` | clipboard.js | Copies text to clipboard with visual feedback |

## See Also
- [JS entry point](./app-static-js.md)
- [Feature modules](./app-static-js-features.md)
