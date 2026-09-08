# metallama/app/static/js/features

Feature-scoped frontend modules, each responsible for one UI section.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `hf/` | HuggingFace browser: search, file listing, download with progress |
| `models/` | Model cards: status display, start/stop buttons, config editing, local/remote badges |
| `system/` | System monitoring: VRAM/RAM gauges, history graphs |
| `theme/` | Theme switcher: light/dark/system toggle with localStorage persistence |

## Key Functions

| Name | Directory | What it does |
|------|-----------|-------------|
| `setupModels()` | models/ | Renders model cards from API, binds start/stop/config buttons |
| `refreshModels()` | models/ | Polls `/api/models` and updates card status (skipped while inline editing) |
| `cardTemplate()` | models/ | Generates card HTML with locality badge (Local/Remote), status, actions |
| `openEditModal()` | models/ | Opens config editor for managed or remote servers |
| `refreshVram()` | system/ | Fetches VRAM status from `/api/system/vram` |
| `refreshRam()` | system/ | Fetches RAM status from `/api/system/ram` |
| `refreshVramGraph()` | system/ | Renders VRAM history chart |
| `refreshRamGraph()` | system/ | Renders RAM history chart |
| `setupThemeSwitcher()` | theme/ | Initializes theme buttons, reads/writes `localStorage` |

## See Also
- [JS entry point](./app-static-js.md)
- [Core modules](./app-static-js-core.md)
