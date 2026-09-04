# Frontend

The frontend is a vanilla HTML/CSS/JS single-page app with no build step. It is served
by FastAPI: `index.html` at `/`, static assets at `/static`.

## Structure

```
static/
  index.html      — UI shell (panels, modals, login)
  logs.html       — standalone log viewer
  styles.css      — all styling + theme variables
  js/
    main.js       — entry point; wires all features together
    core/         — shared utilities
      api.js      — fetch wrapper
      auth.js     — client auth state
      clipboard.js
      download.js
      uiMessage.js
    features/     — one module per UI feature
      models/     — model cards, start/stop, logs, edit/create
      hf/         — HuggingFace search + downloads
      library/    — local model library
      connect/    — connection snippets modal
      system/     — VRAM/RAM status + graphs
      theme/      — theme switcher
```

## Module Wiring

`main.js` imports and calls each feature's `setup*` function during `init()`:
- `setupThemeSwitcher()`
- `setupModels()`
- `setupHfSearch()`
- `setupLibrary()`
- `setupConnect()`

It also handles auth state (login modal, admin toggle) and the binary-missing warning.

## Key Patterns

- **API calls**: all requests go through `core/api.js` `api()`, which adds JSON + auth
  headers and throws on non-OK responses.
- **Auth**: `core/auth.js` stores the token in `sessionStorage` and exposes
  `isAdmin()`, `login()`, `logout()`, `verifyToken()`. The `admin-only` CSS class
  hides admin actions when not logged in.
- **Cross-module hooks**: some modules expose globals on `window` for interop, e.g.
  `window.__metallamaInvalidateModelCache` (models) and
  `window.__metallamaResumeDownload` (hf).
- **Theming**: `document.documentElement.dataset.theme` is `light`/`dark`; preference
  is persisted in `localStorage` (`metallama.theme`), defaulting to `system`.
- **Graphs**: `features/system/index.js` draws VRAM/RAM history on `<canvas>` with
  HiDPI-aware sizing.
- **Per-GPU VRAM**: `features/system/index.js` renders the aggregate VRAM total graph
  first, then a collapsible "Individual GPUs" section (`#vram-gpus-toggle` +
  `#vram-gpus`). Each GPU has a toggleable row (checkbox + live value + mini graph).
  Untracked GPUs are dimmed, moved to the bottom of the list, and their graph is
  hidden. Toggling calls `POST /api/system/vram/gpus/toggle`; the tracked set is
  persisted server-side in `.metallama_gpu_config.json`. The collapsible section's
  open/closed state is persisted in `localStorage` (`metallama.gpusSectionOpen`).
  The total graph is computed on-demand from the per-GPU histories of currently
  tracked GPUs, so untracking a GPU also removes its past data from the total.
- **Reasoning efforts**: the server edit modal provides a master toggle plus
  per-effort checkboxes. Enabling the master selects all inferred values; individual
  values can then be disabled. Server cards display the enabled set as a
  `Reasoning: ...` chip. Enabled values become virtual `name:effort` models in the
  Ollama gateway.

## See Also
- [Architecture](architecture.md)
- [Core JS](../tree/static-js-core.md)
- [Feature JS](../tree/static-js-features.md)
- [Static assets](../tree/static.md)