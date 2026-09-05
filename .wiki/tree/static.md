# metallama/app/static

Static assets served by FastAPI at `/static` and `/` (index.html).

## Files

| File | Purpose |
|------|---------|
| `index.html` | Single-page UI shell (all feature panels, modals, login) |
| `logs.html` | Standalone log viewer page |
| `styles.css` | All styling, including shared controls, dark theme variables, and responsive server-card/library layouts |
| `logo.svg` | Project logo |
| `todo.todo` | Scratch/notes file (not part of the app) |
| `js/` | Frontend ES modules (see core + features tree pages) |

## Notes

- `index.html` is served at `/` via `FileResponse` in `main.py`.
- The UI is vanilla JS with no build step; modules are loaded as ES modules.
- Theme is controlled by `document.documentElement.dataset.theme` (`light`/`dark`).

## See Also
- [Frontend overview](../notes/frontend.md)
- [Core JS](../tree/static-js-core.md)
- [Feature JS](../tree/static-js-features.md)