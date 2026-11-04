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
| `statement.js` | Pure CSV builder for the wallet statement. No DOM, no network, so the test suite executes it under Node. |

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

## Two kinds of page

**App pages** are signed-in screens. They load `api.js` and `ui.js`, mount the
shared chrome and join `APP_PAGES` in `tests/test_web_assets.py`.

**Public and standalone pages** work for a visitor with no session, so they must
not depend on the app shell. They join `NO_SHELL` instead:

| Page | Purpose | Data source |
| --- | --- | --- |
| `index.html` | Landing page | none |
| `prices.html` | Today's data prices before sign-up | public `GET /api/data-plans` only |
| `help.html` | WhatsApp, call and email support, plus the FAQ | none (static, works offline) |
| `privacy.html` | Privacy policy | none |
| `offline.html` | Shown by the service worker with no connection | none, fully self-contained |

Public pages that render supplier-supplied strings (the price list) must pass
every value through `esc()` before it reaches `innerHTML`;
`tests/test_public_price_list.py` enforces it.

The support number is stored in `help.html`, `offline.html` and `privacy.html`.
`tests/test_help_and_support.py` fails if the copies drift apart.

## Theme and network detection

* `theme.js` loads synchronously in the `<head>` of every app page so the saved
  choice (`melodexsTheme`: `light` or `dark`; absent means follow the phone) is
  applied before first paint. Use the colour tokens in `styles.css`; do not
  hard-code colours on cards.
* `network-detect.js` is a pure module (no DOM, no network) holding the NCC
  prefix table. `bindNetworkDetection` wires a phone input to a page's network
  selector. A prefix is a hint, not proof (number portability), so the page must
  show what was detected and keep a manual choice.

## Customer-facing text

Transaction descriptions are stored as `customer text | internal note | ...`.
Everything after the first ` | ` is bookkeeping (supplier names, reconciliation
notes) and must never be shown to a customer. Use
`MELODEXS_STATEMENT.customerDescription()`; the Wallet list, detail view,
official receipt and CSV export all do.

## Rules

* Never hardcode a colour: use a token. An undeclared token inherits silently and
  produces invisible text, which `tests/test_css_tokens.py` catches.
* A new page joins `APP_PAGES` in `tests/test_web_assets.py`, or the suite fails.
* Phone layout is the default; desktop is the `min-width: 900px` override.
* Every control needs a label; icons carry `aria-hidden`.
