# metallama/app/static/js/core

Shared frontend utilities used across feature modules. ES modules.

## Files

| File | Purpose |
|------|---------|
| `api.js` | `api()` fetch wrapper: JSON headers, auth header, error extraction |
| `auth.js` | Client-side auth state: token storage, login/logout, verify, admin state |
| `clipboard.js` | `copyToClipboard()` with fallback for non-secure contexts |
| `download.js` | `downloadMarkdownFile()` — client-side `.md` file download |
| `uiMessage.js` | `setConfigMessage()` — status/error banner with copy-on-click for errors |

## Key Classes & Functions

| Name | File | What it does |
|------|------|-------------|
| `api()` | api.js | Wraps `fetch`, adds JSON + auth headers, throws on non-OK |
| `checkAuthEnabled()` | auth.js | Queries `/api/auth/status` and caches result |
| `isAdmin()` | auth.js | True if auth off or a valid token is held |
| `verifyToken()` | auth.js | Validates stored token against server; clears if invalid |
| `login()` / `logout()` | auth.js | Login/logout flow with sessionStorage token |
| `authHeader()` | auth.js | Returns `Bearer <token>` or empty string |
| `copyToClipboard()` | clipboard.js | Clipboard write with textarea fallback |
| `downloadMarkdownFile()` | download.js | Creates and clicks a Blob download anchor |
| `setConfigMessage()` | uiMessage.js | Shows status/error message; errors copyable on click |

## See Also
- [Frontend overview](../notes/frontend.md)
- [Feature modules](../tree/static-js-features.md)