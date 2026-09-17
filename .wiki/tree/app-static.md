# metallama/app/static

Frontend static assets served by FastAPI at `/static`.

## Files

| File | Purpose |
|------|---------|
| `index.html` | Main HTML page: banner, model cards, system info |
| `chat.html` | Standalone chat page served at `/chat` (conversations sidebar, model picker, image attachments) |
| `logs.html` | Standalone log viewer page |
| `styles.css` | Full stylesheet with light/dark theme support via CSS custom properties |
| `assets/` | Images: logo, banner |
| `js/` | JavaScript application code (see [app-static-js](./app-static-js.md)) |

## See Also
- [JavaScript modules](./app-static-js.md)
- [Architecture overview](../notes/architecture.md)
