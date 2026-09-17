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
      modal.js    — shared overlay dismissal
      uiMessage.js
    features/     — one module per UI feature
      chat/       — standalone /chat page (conversations, streaming, images)
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

Navigation between the two pages is plain links: the main page header has a Chat
pill (`.chat-link`, `index.html`) linking to `/chat`, and the chat page brand
(`.chat-brand`, `chat.html`) links back to `/`.

## Key Patterns

- **API calls**: all requests go through `core/api.js` `api()`, which adds JSON + auth
  headers and throws on non-OK responses.
- **Auth**: `core/auth.js` stores the token in `sessionStorage` and exposes
  `isAdmin()`, `login()`, `logout()`, `verifyToken()`. The `admin-only` CSS class
  hides admin actions when not logged in.
- **Cross-module hooks**: some modules expose globals on `window` for interop, e.g.
  `window.__metallamaInvalidateModelCache` (models) and
  `window.__metallamaResumeDownload` (hf).
- **Modal dismissal**: every overlay (`edit`, `restart`, `defaults`, `connect`,
  `login`) registers via `core/modal.js` `registerModal(modal, close)`, which owns
  two concerns:
  - *Backdrop click*: only closes when the press **both** started and ended on the
    overlay itself. A plain `click` listener comparing `event.target === overlay` is
    wrong — `click` is dispatched on the nearest common ancestor of the pointerdown
    and pointerup targets, so a text selection or scrollbar drag that is released on
    the backdrop produces a click targeting the overlay and would destroy the modal
    mid-edit.
  - *Escape*: a single shared document listener closes only the **front-most** visible
    overlay, ignores `defaultPrevented` events, and defers to an open native
    `<select>` popup. It uses `stopImmediatePropagation()` so other document-level
    Escape listeners don't act on the same keypress.
  Stacking order is DOM order (`topmostOpenModal()`), so overlay elements must stay
  ordered in `index.html` with the most-recently-opened last.
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
- **Reasoning ("thoughts") display**: the chat page renders a model's
  `reasoning_content` in a dedicated collapsible "Thoughts" chat message
  (`.chat-msg.thoughts`, a single `<details>` whose summary reads "Thought for Xs")
  above the answer. The summary uses a 💭 icon and muted text; the body renders as
  Markdown (including code blocks) with a left accent border. It streams live during
  generation and is persisted on the assistant message (`msg.reasoning` plus
  `msg.reasoning_secs` for the duration), included in exports, and restored on
  import.
- **Message layout**: assistant messages span the full column width (within the
  1000px bounds) as a darker panel block (`.chat-msg.assistant`, `width: 100%`,
  `background: var(--chat-surface)`, rounded corners); user messages are
  right-aligned, accent-tinted bubbles that shrink to their content
  (`.chat-msg.user`, `max-width: 85%`, `width: fit-content`, rounded corners).
  The message list (`.chat-messages`) is constrained to the same 1000px column
  as the input bar and centered, so history never spans the full viewport on
  wide screens (on mobile the viewport is narrower than the column, so it
  naturally fills the width). The message list carries `1.25rem` horizontal
  padding at all widths, matching the input bar, so bubbles don't touch the
  sidebar or scrollbar and stay aligned with the textarea. The meta row is a
  small uppercase label:
  user messages use the accent color, assistant messages use the green accent
  (matching the model selector pill). Scrollbars are thin and subtle, matching
  the dark theme (`scrollbar-width: thin` + `::-webkit-scrollbar` styling).
- **Chat surfaces**: the chat page uses two dedicated surface variables —
  `--chat-surface` (`#1a1817`, darker than `--panel`) for the LLM message
  background, sidebar, textarea, and code blocks; and `--chat-surface-raised`
  (`#211e1d`) for code headers, menus, and table headers. This keeps the chat
  area visually distinct from the main app's lighter panels.
- **Chat controls**: the topbar icon buttons (`.chat-icon-btn`, e.g. expand/new)
  and the sidebar collapse button use a brighter foreground (`var(--text)`) and a
  brighter border (`var(--line-bright)`) on the raised chat surface so they're
  clearly visible against the dark background. The conversation list items use
  `var(--muted)` text, brighten to `var(--text)` on hover, and the active item
  gets an accent-tinted background plus a left accent bar
  (`box-shadow: inset 2px 0 0 var(--accent)`).
- **Chat image attachments (vision models)**: the `/chat` composer accepts images
  via the file picker, clipboard paste, and drag & drop. The attach button is
  enabled only when the selected model advertises `vision` in its `capabilities`
  (from `/ollama/api/tags`). Images are downscaled to a 1024px long edge and
  re-encoded (PNG stays PNG for text/screenshots, everything else becomes JPEG —
  never WebP, which llama.cpp's `stb_image` cannot decode), capped at 8 per
  message. Pixels are stored as Blobs in `features/chat/imageStore.js`, a
  content-addressed IndexedDB store keyed by SHA-256 (deduplicates repeats, with
  an in-memory fallback when IndexedDB is unavailable). Conversations keep only
  `{id, w, h, bytes}` refs, so the localStorage conversation JSON stays small.
  On send the refs are hydrated to `data:` URLs for the gateway, which already
  converts Ollama `images` to OpenAI `image_url` content parts. User bubbles show
  click-to-enlarge thumbnails, exports embed the images as data URLs, imports
  re-store them, and the context chip adds a rough per-image token estimate until
  the server's real `prompt_eval_count` arrives.

## See Also
- [Architecture](architecture.md)
- [Core JS](../tree/static-js-core.md)
- [Feature JS](../tree/static-js-features.md)
- [Static assets](../tree/static.md)