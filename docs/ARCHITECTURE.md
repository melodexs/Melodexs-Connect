# Architecture

MELODEX is two deployables that share one origin-agnostic contract.

```
apps/web  (static site, CDN)      apps/api-python  (FastAPI on Render, Oregon)
  HTML pages per feature  ──────▶   /api/*  JSON API
  styles.css, ui.js, api.js         provider adapters ──▶ VTU suppliers
  sw.js, PWA manifest               PostgreSQL (Neon, us-west-2)
```

## Frontend

* Plain HTML/CSS/vanilla JS. No build step: what is committed is what is served.
* `api.js` patches `window.fetch` so every page can call relative `/api/*`
  paths; in production those are rewritten to the API origin. It also attaches
  the session bearer token when present.
* `ui.js` owns the shared chrome: app bar, bottom navigation (mobile), the
  desktop sidebar (every feature, with icons), modals, formatting helpers and
  the boot indicator.
* `sw.js` caches the shell for offline use. Navigations are network-first with
  a cached fallback; `/api/*` is never cached.

## API

* One FastAPI app. Every customer route is authenticated by a session: a signed
  cookie plus, for browsers that block third-party cookies, the same signed
  value as an `Authorization: Bearer` token.
* Money paths follow one shape: verify the purchase PIN, guard against
  duplicates, revalidate the price against the live catalogue, debit atomically,
  then fulfil. Supplier failures that are not provably "never happened" leave the
  transaction `pending` for reconciliation instead of guessing.
* Provider integrations live behind adapters (`app/provider_*.py`) registered in
  `app/provider_registry.py`; see [PROVIDERS.md](PROVIDERS.md).
* Purchases that end `pending` are swept by a rate-limited background requery on
  `/api/status` pings; see [OPERATIONS.md](OPERATIONS.md).

## Data

PostgreSQL in production, SQLite for tests. The schema is validated read-only at
startup against a reviewed expectation (`app/schema_check.py`) and the process
refuses to boot on a mismatch, so accidental DDL in production is impossible.
See [DATABASE.md](DATABASE.md).

## Why the two deployments share a region

The API and the database both run in `us-west-2`. An earlier layout kept the
database in London while the API ran in Oregon; each statement cost roughly
0.6s of network time, which made login feel slow. Same-region co-location took
login from ~1.8s to ~0.67s. See
[adr/0002-region-co-location.md](adr/0002-region-co-location.md).
