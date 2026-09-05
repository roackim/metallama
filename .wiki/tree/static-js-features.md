# metallama/app/static/js/features

One ES module per UI feature. Each exports a `setup*` function called from `main.js`.

## Files

| File | Purpose |
|------|---------|
| `models/index.js` | Model cards: compact metadata/actions layout, start/stop, logs, slots, edit/create modal, filters |
| `hf/index.js` | HuggingFace search panel + download orchestration |
| `library/index.js` | Local model library: inventory, partial downloads, compact Serve/Rename/Delete action groups |
| `connect/index.js` | "Connect" modal with Ollama/OpenAI/curl snippets |
| `system/index.js` | VRAM/RAM status + history graphs (canvas); per-GPU VRAM toggles + mini graphs |
| `theme/index.js` | Dark/light/system theme switcher |

## Key Classes & Functions

| Name | File | What it does |
|------|------|-------------|
| `setupModels()` / `refreshModels()` | models/index.js | Renders model cards and polls status |
| `openCreateForModel()` | models/index.js | Opens the create/edit modal (used by HF + library) |
| `setupHfSearch()` | hf/index.js | Wires HF search input, results, and downloads |
| `refreshLibrary()` | library/index.js | Refreshes the local model library list |
| `setupConnect()` | connect/index.js | Wires the connect modal + snippet generation |
| `refreshVram()` / `refreshRam()` | system/index.js | Poll VRAM/RAM status |
| `refreshVramGraph()` / `refreshRamGraph()` | system/index.js | Draw history graphs on canvas (aggregate + per-GPU) |
| `renderGpuList()` | system/index.js | Renders per-GPU toggle rows (tracked first, untracked dimmed at bottom with graph hidden) |
| `setupThemeSwitcher()` | theme/index.js | Applies and persists theme preference |

## See Also
- [Frontend overview](../notes/frontend.md)
- [Core utilities](../tree/static-js-core.md)