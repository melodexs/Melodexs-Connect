# Changelog

Notable changes, newest first. Dates are deployment dates.

## November 2026

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
