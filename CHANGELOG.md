# Changelog

Notable changes, newest first. Dates are deployment dates.

## November 2026

### Documentation and guard rails
* Added the guides that were living in people's heads: architecture, frontend,
  API, database, providers, operations, deployment, testing and local setup, plus
  an index and two decision records.
* Added correctness-only lint (CI and pre-commit), a Makefile that forces a
  scratch test database, an `.editorconfig`, Dependabot for pip and Actions, and
  a pull-request template that asks for evidence.
* New tests cover the user payload (no credential leaks), Nigerian phone
  validation, the 2% markup rounding, session cookie flags, safe configuration
  defaults, page/asset wiring, the PWA manifest, the service worker, the
  navigation contract, the desktop shell layout, `security.txt`, the crawl files,
  provider capabilities, the health and error contracts and repository hygiene
  (no committed secrets or database files).
* Fixed two real defects the new tests found: `privacy.html` pointed at two icons
  that do not exist, and `security.txt` had no `Policy` line.
* Accessibility: keyboard focus is now visible on every control, the desktop
  shell honours `prefers-reduced-motion`, and receipts print without the chrome.

### Database moved next to the application
Production PostgreSQL moved from London to `us-west-2`, the same region as the
API. Login went from ~1.8s to ~0.67s, page boot to 0.14s and catalogue reads to
0.24s. The London project is retained as a rollback copy.

### Faster sign-in
* Removed a fixed 700ms (login) and 900ms (registration) wait before redirecting.
* `/api/bootstrap` and `/api/session` resolve the session owner and profile in a
  single statement.
* Sign-in pages warm the database while the visitor types.

### Desktop shell
A fixed sidebar lists every feature with its icons, the content column widens and
the dashboard uses two columns. Phones keep the bottom bar.

### Providers
* RizPay adapter corrected to the supplier's documented contract (still retired).
* GN Data adapter prepared and registered, disabled without credentials.

## October 2026

### iOS sign-in fixed
`onrender.com` is a public suffix, so the site and the API are different sites and
Safari blocks the session cookie as third-party. Sign-in now also returns a session
token that the app sends as a bearer credential.

### Landing page
Defined the missing `--bluegray` token that made body copy render dark-on-dark,
and added a test that fails when a colour token is used but never declared.

### Billers, PWA, security headers
Electricity, TV and education result PINs; installable PWA with an offline page;
CSP and companion headers on both deployables.

### Provider platform
ISQUAREDATA activated as the primary provider with a 2% markup, WiseSub retained,
airtime pinned to WiseSub, mixed catalogue and automatic requery for pending
purchases.
