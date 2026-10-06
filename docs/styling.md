# Metallama Styling Guide

Reference for styling new UI features (e.g. the chat window) so they match the
existing app. All values below are extracted from `metallama/app/static/styles.css`
(~2700 lines, single file, no build step).

**Golden rule: never hardcode colors or sizes — always use the CSS variables in
`:root`.** The entire theme is driven by them; a future light theme only works if
new code respects this.

---

## 1. Design tokens (`:root`)

### Colors (dark, warm charcoal + violet accent)

| Variable | Value | Use |
|---|---|---|
| `--bg` | `#0a0a09` | Page background |
| `--panel` | `#1a1714` | Card / modal / toast backgrounds |
| `--panel-raised` | `#211d1a` | Inputs, secondary buttons, graph wells (one step above panel) |
| `--line` | `#403a35` | Default borders |
| `--line-bright` | `#62574f` | Hovered/active borders, graph canvas border |
| `--text` | `#f4f4f5` | Primary text |
| `--muted` | `#a1a1aa` | Secondary text, inactive labels |
| `--text-dim` | `#52525b` | Tertiary text (subtitles, hints) |
| `--accent` | `#6d5dfc` | **Primary brand color** — focus rings, primary buttons, active states |
| `--blue` | `#9b8cff` | Links, active utility buttons |
| `--gold` | `#e9d5ff` | Text on accent-active toggles |
| `--green` | `#22c55e` | Online status, success |
| `--red` | `#ef4444` | Errors, destructive actions |
| `--bg-hover` | `#29221e` | Hover background for raised elements |
| `--bg-active` | `rgba(109, 93, 252, 0.16)` | Active/selected tint (accent at 16%) |
| `--brand-glow` | `rgba(109, 93, 252, 0.24)` | Focus box-shadow glow |

Status tints are derived inline with `color-mix(in srgb, var(--green) 14%, var(--panel))`
— do the same for new status colors instead of inventing hex values.

### Sizing / shape

| Variable | Value | Use |
|---|---|---|
| `--border-size` | `1px` | All borders (use in `border: var(--border-size) solid var(--line)`) |
| `--control-height` | `32px` | Header action buttons |
| `--control-radius` | `5px` | Small controls (header actions, utility buttons) |
| `--radius-sm` | `7px` | Buttons, inputs, cards |
| `--radius` | `8px` | Larger containers |

Pill shape: `border-radius: 999px` (badges, chips, toasts).

---

## 2. Typography

- **Base font**: `ui-sans-serif, system-ui, -apple-system, sans-serif`, body size
  `14px`, line-height `1.45`. Root `html` is scaled to `font-size: 118.75%`, so
  most component sizes are written in `rem`/fractional `rem` (e.g. `0.78rem`).
- **Monospace** (model names, values, logs, code): `ui-monospace, "SF Mono", Menlo, Consolas, monospace`.
- **Weight scale**: 650 is the house weight for buttons/labels; 700–750 for titles.
  Titles use tight tracking: `letter-spacing: 0.01em`.
- **Uppercase micro-labels** (section eyebrows, metric names):
  `font-size: 0.74rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;`

Type scale in practice:

| Role | Size / weight | Example class |
|---|---|---|
| Page title (hero) | `2rem` / 800 | `.hero-title` |
| Panel title | `1rem` / 750 | `.side-title` |
| Card title | `1.15rem` / 750 | `.card h3` |
| Body text | `14px` (body) | — |
| Secondary text | `0.82–0.86rem` | `.info-banner-block`, `.ui-message` |
| Small labels/buttons | `0.72–0.78rem` / 650 | `.app-control`, `.header-action` |
| Micro badges | `0.62–0.74rem` / 700 uppercase | `.locality-badge`, `.status-badge` |

---

## 3. Layout

- Page: `.container` — `max-width: 1920px; margin: 2.5rem auto; padding: 0 1rem 5rem`.
- Two-column grid (collapses to one column below **1450px**):
  ```css
  .layout-grid { display: grid; grid-template-columns: minmax(0, 3fr) minmax(420px, 1fr); gap: 0.9rem; }
  ```
- Left = `.main-col` (stacked panels), right = `.side-col` (`position: sticky; top: 1rem`).
- **Panels are flat**: `.main-panel` / `.side-panel` have *no* background, border or
  radius — they're just padded regions of the page. Depth comes from **cards**, not panels.
- Mobile breakpoint at `720px`: root font drops to `100%`, body to `13px`.

### Where a chat panel fits

Add it as another `<section class="main-panel">` inside `.main-col` (like the
Servers and Model Library sections), or as a full-width section above/below them.
Use the standard head pattern:

```html
<section class="main-panel" id="chat-panel">
  <div class="panel-head">
    <div class="panel-head-left">
      <h2 class="side-title">Chat</h2>
      <!-- optional status chip -->
    </div>
    <div class="panel-head-right">
      <!-- .header-action buttons / model select -->
    </div>
  </div>
  ...
</section>
```

`.panel-head` is flex, space-between, wraps, `margin-bottom: 1.1rem`.

---

## 4. Components (copy these patterns)

### Cards — the unit of visual depth

```css
background: var(--panel);
border: var(--border-size) solid var(--line);
border-radius: var(--radius-sm);          /* 7px */
box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
```

Optional left accent stripe for state: `border-left: 4px solid <state-color>`
(model cards use this). A chat message bubble can follow the same recipe — user
vs assistant distinguished by a `--card-accent`-style custom property or subtle
background shift (`var(--panel)` vs `var(--panel-raised)`), not by bright colors.

### Buttons

Base `button`: light fill is *not* used in practice; the real system (from the
"Balanced hybrid visual pass", which overrides earlier rules — **follow this one**):

| Class | Look | Use for |
|---|---|---|
| `.btn-primary` | transparent bg, `1px solid var(--accent)`, accent text; hover: accent 12% fill | Main CTA (Send message) |
| `.btn-secondary` | `var(--panel-raised)` bg, `--line` border, text color; hover: `--bg-hover` + `--line-bright` | Secondary actions |
| `.btn-danger` | transparent, red border/text; hover: solid red fill, white text | Destructive (Delete conversation) |
| `.app-control` | small pill-ish control: 30px min-height, `--panel-raised`, 0.72rem/650, radius 5px | In-card utility buttons — **use this for chat toolbar icons** (stop, clear, attach) |
| `.chip-btn` | transparent, rounded-full, muted; `.active`: panel bg + shadow | Filter chips / toggles (e.g. web-search toggle) |

Button behavior: `transition: opacity .15s, background .15s, border-color .15s, transform .05s`;
hover = `opacity: 0.75` (unless overridden); active press = `transform: scale(0.98)`;
disabled = `opacity: 0.3`.

### Inputs / selects / textarea

- Background `var(--panel-raised)`, border `var(--border-size) solid var(--line)`,
  radius `var(--radius-sm)`.
- **Focus**: `border-color: var(--accent)` + `box-shadow: 0 0 0 2px var(--brand-glow)`.
  (Global fallback is a 2px accent outline on `:focus-visible`.)
- The chat input box should be a `<textarea>` styled exactly like `.modal-body textarea`,
  auto-growing, with the Send button as `.btn-primary` in a flex row below or beside it.

### Status badges (reuse for model online/offline in chat header)

`.status-badge`: pill, `0.74rem/700` uppercase, leading 8px dot via `::before`,
color + tinted bg per state: `.online` (green), `.offline` (muted), `.starting`
(amber `#d6a84f`) with a `status-pulse` opacity animation.

### Toast / inline messages

- Global toast: `.ui-message` — fixed bottom-center pill, panel bg, shadow;
  `.error` variant tints border/text red. Drive it via the existing
  `core/uiMessage.js`, don't build a new one.
- Inline banner (warnings): `.info-banner` / `.binary-warning` pattern — panel or
  amber bg, **4px left accent border**, small text.

### Badges & chips

`.summary-chip`: tiny pill (`0.76rem/650`, muted on `--bg`, line border) for counts
next to titles (e.g. "3 online"). Good fit for a token-count indicator in chat.

---

## 5. Theming mechanics

- Theme is applied via `document.documentElement.dataset.theme` — currently **dark only**
  (`features/theme/index.js` hardcodes `"dark"`), but the variable system is built so a
  light theme can be added by redefining `:root` vars under `[data-theme="light"]`.
- Consequences for new code:
  - Only reference colors through variables (or `color-mix()` on them).
  - Avoid pure `#fff`/`#000`; the one exception is `.binary-warning`, which uses a fixed
    amber palette (intentional high-contrast warning).
  - Shadows are dark and soft: `rgba(0,0,0,0.3–0.45)`; modal overlay adds `backdrop-filter: blur(3px)`.

---

## 6. Motion & misc conventions

- Animations are subtle and few: `status-pulse` (opacity 1.2s loop for "starting"),
  `loading-slide` (model loading strip). A streaming cursor in chat should be a simple
  opacity blink on the same order (~1s), not a bounce.
- Hidden state: toggle `.is-hidden` (`display: none !important`) — never inline styles.
- Admin-gated UI: add class `admin-only` (hidden unless logged in as admin).
- Cross-module hooks live on `window.__metallama*` if the chat feature needs to react
  to model start/stop events from the models module.
- CSS is one flat file, organized by `/* ── Section ─── */` banner comments; append a new
  `/* ── Chat ─────────────────────────────── */` section at the end (after "Balanced hybrid
  visual pass" so your rules win the cascade if they need to).

## 7. Quick recipe: chat message bubble

```css
.chat-msg {
  padding: 0.6rem 1rem;
  background: var(--panel);            /* assistant */
  border: var(--border-size) solid var(--line);
  border-radius: var(--radius-sm);
}
.chat-msg.user {
  background: var(--panel-raised);     /* or accent-tinted: color-mix(in srgb, var(--accent) 8%, var(--panel)) */
}
.chat-msg .chat-meta {                 /* model name / time line */
  font-size: 0.7rem; font-weight: 650; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--text-dim);
  margin-bottom: 0.3rem;
}
.chat-msg .chat-body { white-space: pre-wrap; word-break: break-word; }
```
