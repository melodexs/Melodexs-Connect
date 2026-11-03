# Frontend

Plain HTML, one stylesheet, two scripts. No build step: the committed files are
what the CDN serves.

## Files

| File | Responsibility |
| --- | --- |
| `styles.css` | The whole design system: tokens in `:root`, components, the desktop shell, print and reduced-motion rules. |
| `api.js` | Rewrites relative `/api/*` to the API origin and attaches the session bearer token. Loaded first on every page. |
| `ui.js` | Shared chrome: app bar, bottom bar, desktop sidebar, modals, formatting, boot indicator. |
| `pwa.js`, `sw.js`, `manifest.webmanifest` | Installability, offline shell, install prompt handling. |

## Page shape

```html
<body class="app-body">
  <div id="appbar"></div>          <!-- ui.js fills this -->
  <main class="page">…</main>
  <nav id="bottom-nav"></nav>      <!-- mobile -->
  <div id="desktop-tabs"></div>    <!-- legacy pill row, hidden when the sidebar exists -->
  <div id="boot-loading">Connecting…</div>
</body>
```

Pages call `MELODEXS_UI.mountChrome("<feature>")` and finish boot with
`UI.bootDone()`. The sidebar is also built on `DOMContentLoaded`, so navigation
survives a page whose own boot fails.

## Rules

* Never hardcode a colour: use a token. An undeclared token inherits silently and
  produces invisible text, which `tests/test_css_tokens.py` catches.
* A new page joins `APP_PAGES` in `tests/test_web_assets.py`, or the suite fails.
* Phone layout is the default; desktop is the `min-width: 900px` override.
* Every control needs a label; icons carry `aria-hidden`.
