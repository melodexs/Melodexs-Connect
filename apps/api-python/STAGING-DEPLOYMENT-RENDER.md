# Render Deployment Guide — Python API (staging)

Exact steps for creating the **Python staging web service** on Render. This
guide was prepared from the repository's actual structure on 2026-10-15.
The production Node.js API service and the production frontend service are
NOT touched by anything here.

## Current services (verified via the Render API on 2026-10-15)

| Service | URL | Runtime | Status |
|---|---|---|---|
| Production API | `https://melodexs-connect-api.onrender.com` | Node.js (`rootDir: apps/api`) | LIVE, unchanged |
| Production frontend | `https://melodexs-connect.onrender.com` | Render static site | LIVE, unchanged |
| Python staging API | `https://melodexs-connect-api-staging.onrender.com` | Python (Uvicorn) | LIVE (deployed 2026-10-15) |
| Staging frontend | `https://melodexs-connect-staging.onrender.com` | Render static site | LIVE (deployed 2026-10-15) |
| Staging PostgreSQL | internal (Render private network) | Render PostgreSQL, free tier | LIVE; fresh empty DB; expires 2026-11-14 |

The staging API was deployed from branch `fix/staging-proxy-headers` at
commit `f556180` (content identical to master `87c1327` after PR #6). The
base schema and migrations 001–003 were applied as a one-shot before first
boot (see STAGING-TEST-EVIDENCE.md for the full record). The steps below are
retained as the reproducible procedure and the reference for any
re-provisioning.

## Facts established from the code (not guesses)

- **Framework:** FastAPI + Uvicorn (`apps/api-python/requirements.txt` pins
  `uvicorn[standard]>=0.30,<1`; no Node.js is needed to run the API).
- **Entry point:** `app.main:app`, with the app package at
  `apps/api-python/` (module run as `app.main` from an `--app-dir`).
- **Binding:** the start command binds `0.0.0.0` and reads `$PORT`
  (falls back to 3000 locally). Render supplies `$PORT`; no change needed.
- **Health check:** `GET /api/status` returns
  `{"success":true,"message":"MELODEXS CONNECT API is running"}` with HTTP
  200. It is a pure liveness probe (no database call), so it is the correct
  Render **Health Check Path**.
- **Static frontend:** the API also mounts `apps/web/` at `/` using a
  repo-root-relative absolute path, so the service serves the frontend at
  the API origin too (useful as a same-origin smoke target).
- **Proxy headers:** behind Render's proxy, `--proxy-headers` and
  `FORWARDED_ALLOW_IPS` are required for correct rate-limit attribution
  (see PR #6). Set `FORWARDED_ALLOW_IPS` per Render's current documentation.
- **Startup validation:** with `NODE_ENV=production`, missing/short
  `SESSION_SECRET`, a non-PostgreSQL `DATABASE_URL`, or
  `WISESUB_ENVIRONMENT != live` each refuse to start (verified locally
  against a disposable PostgreSQL database; see STAGING-TEST-EVIDENCE.md).
  A crashed staging deploy with red logs is therefore a configuration
  signal, not a code failure.
- **TLS:** the app requires the `DATABASE_URL` scheme to be PostgreSQL in
  production but does not force `sslmode`; Render's internal
  `DATABASE_URL` works as injected. Add TLS parameters to the URL only per
  Render's current documentation — do not invent values.
- **Secrets:** no `.env` file is tracked in Git (verified); all secrets go
  into Render's Environment settings. `apps/api-python/env.example` is a
  value-less template and the only variable list needed.

## Dashboard step 1 — Create the staging PostgreSQL database

1. Render dashboard → **New → PostgreSQL**.
2. Name it clearly as staging (for example `melodexs-connect-staging-db`).
3. Region: same region as the staging API service will use.
4. **This database is NOT the production database.** After creation, note
   the generated `DATABASE_URL` (Render keeps it in the database's
   dashboard page — never paste it into chat, commits, or tickets).
5. Create the staging API service (step 2) in the same region and group so
   it can read the `DATABASE_URL` via the **From database** secret link.

## Dashboard step 2 — Create the Python staging web service

1. **New → Web Service** → connect the `melodexs/Melodexs-Connect` repo.
2. **Name:** clearly staging (for example
   `melodexs-connect-api-staging`).
3. **Region:** same as the staging database.
4. **Branch:** `fix/staging-proxy-headers` (contains the proxy-header
   start command and this guide) — or `master` after PR #6 is merged.
   Never point this service at the production Node service's settings.
5. **Runtime:** Python 3 (Render's native Python environment).
6. **Root Directory:** leave blank (repo root). The app resolves its own
   paths from the module location, so this also works if you later prefer
   `apps/api-python` — repo-root default is the tested configuration.
7. **Build Command:**
   `pip install -r apps/api-python/requirements.txt`
8. **Start Command** (verified against the actual entry point):
   `python3 -m uvicorn app.main:app --app-dir apps/api-python --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips ${FORWARDED_ALLOW_IPS:-127.0.0.1}`
9. **Health Check Path:** `/api/status`
10. **Instance type:** smallest plan is fine for staging.

## Dashboard step 3 — Environment variables (staging service)

Set these in the staging service's **Environment** tab (never in Git):

| Variable | Value |
|---|---|
| `NODE_ENV` | `production` (exercises the real production code paths) |
| `DATABASE_URL` | link from the staging database created in step 1 |
| `SESSION_SECRET` | generate a fresh 32+ character random value |
| `CHEAPDATA_PUBLIC_URL` | the staging frontend URL from step 4 (CORS allow-list) |
| `FORWARDED_ALLOW_IPS` | Render's proxy addresses, per Render's current docs |
| `WISESUB_ENVIRONMENT` | `live` (required by startup validation) |
| `WISESUB_API_KEY` / `WISESUB_API_SECRET` | provider sandbox credentials |
| `WISESUB_BASE_URL` | sandbox endpoint if the provider documents one |
| `PAYSTACK_SECRET_KEY` | Paystack **test** key (`sk_test_...`) |
| `PAYSTACK_WEBHOOK_SECRET` | Paystack test webhook secret, if used |
| `BREVO_API_KEY` / `BREVO_FROM_EMAIL` / `BREVO_FROM_NAME` | Brevo sandbox/test values |

The full annotated list is `apps/api-python/env.example`.

## Dashboard step 4 — Create the staging frontend

1. **New → Static Site** → same repo.
2. **Branch:** a staging branch where every
   `<meta name="api-base-url">` tag's `content` is set to the staging API
   URL (see step 5). Do NOT edit production's meta tags.
3. **Build Command:** none needed; the site is static.
4. **Publish Directory:** `apps/web`
5. After both staging services exist, update the staging branch's meta
   tags and `CHEAPDATA_PUBLIC_URL` to each other's URLs.

## Step 5 — Point the staging frontend at the staging API

The frontend resolves its API origin ONLY from the
`<meta name="api-base-url" content="...">` tag in each HTML page (14 pages)
plus the `PRODUCTION_API_URL` constant in `apps/web/api.js`. For staging:

1. Create a branch, for example `staging/frontend-config`.
2. Set the meta content on all 14 pages to the staging API URL:
   `grep -rl 'name="api-base-url"' apps/web | xargs sed -i
   's#content="[^"]*"#content="https://YOUR-STAGING-API.onrender.com"#'`
   (an automated frontend-contract test verifies no page is missed).
3. Leave `API_TARGET_IS_PYTHON = false` in `api.js` until the staging
   walkthrough passes, then flip it on the staging branch to exercise the
   category/reconciliation UI.
4. The hosted-page localhost guard means a staging page can never be
   redirected to a developer machine by mistake.

## Step 6 — Post-deploy verification (run in this order)

1. Service log shows `Uvicorn running on http://0.0.0.0:$PORT` — no
   `RuntimeError: Missing or invalid production configuration`.
2. `GET /api/status` returns 200 (Render health check green).
3. Logs contain no secrets or customer data (grep the log for known
   secret substrings — expect zero matches).
4. Registration → login → logout works on the staging frontend with the
   `melodexs_session` cookie (`Secure; HttpOnly; SameSite=none` over
   staging HTTPS).
5. Purchase flows with provider **sandbox** credentials; Paystack test
   webhook pointed at
   `https://YOUR-STAGING-API.onrender.com/api/paystack/webhook`.
6. Admin login and admin-only operations.
7. Then the CUTOVER-CHECKLIST.md browser walkthrough, executed against
   staging.

## Blocked items (owner actions)

Creating the services, linking the database, and providing sandbox
credentials all require Render-dashboard and provider-dashboard access
that this workspace does not have. Everything else above is verified from
the repository itself. Production Node.js service: untouched, keep it.

## Deployed staging configuration (actual, 2026-10-15)

- **Build command:** `pip install -r apps/api-python/requirements.txt`
- **Start command (working form):**
  `python3 -m uvicorn app.main:app --app-dir apps/api-python --host 0.0.0.0 --port $PORT --proxy-headers`
- **Environment variables (staging):** `NODE_ENV=production`,
  `DATABASE_URL` (Render **internal** connection string of the staging
  database), `SESSION_SECRET`, `WISESUB_ENVIRONMENT=live`,
  `CHEAPDATA_PUBLIC_URL` (staging frontend URL),
  `FORWARDED_ALLOW_IPS=*` (Uvicorn reads this natively; see below).
- **Free-tier facts established by deploy logs:**
  - Pre-deploy commands and one-off jobs cannot run (paid instance types
    only). Migrations were applied via a temporary start command and the
    normal command restored afterwards.
  - Shell default expansion (`${VAR:-default}`) in the start command is not
    usable — it broke a deploy. Pass knobs as environment variables
    instead; Uvicorn picks up `FORWARDED_ALLOW_IPS` on its own.
  - The Render API env-var `PUT` endpoint **replaces the whole variable
    set** — always submit the complete list, never a single key.
  - The external (public) database hostname failed SSL from the web
    service; the **internal** connection string is the correct value for
    `DATABASE_URL`.
  - Log retention is minutes on the free tier; capture evidence promptly.
  - `FORWARDED_ALLOW_IPS=*` trusts Render's managed proxy (whose IPs are
    not enumerated in the documentation relied on). The staging service
    port is only reachable through Render's edge, so this is acceptable
    for staging; tighten to Render's published proxy ranges before any
    production use.

## Remaining owner actions (staging)

1. **Remove the Pre-Deploy Command** in the staging service dashboard
   (Settings → Build & Deploy). A one-shot migration script from the
   initial provisioning is still configured; the Render API cannot clear it.
   It never runs on the free tier, but a plan upgrade would run migrations
   automatically on every deploy, which MIGRATION-STAGING.md forbids.
2. Configure provider **sandbox/test credentials** (WiseSub, Paystack
   test keys, Brevo test) on the staging service to unblock provider-flow
   verification and catalog sync.
3. Note the staging PostgreSQL **expires 2026-11-14** (free tier);
   re-provision or upgrade before then if staging must persist.

## Latent production risk recorded (no action taken)

Master's root `package.json` `start` now launches the Python API (PR #5/#6).
Production is unaffected because its service uses `rootDir: apps/api` and
boots Node from the workspace `apps/api/package.json`. But if the production
service's root directory were ever changed to the repo root, the next deploy
would attempt Python, whose startup schema check hard-fails against the
unmigrated production database (crash-loop, not silent divergence). Do not
change the production root directory or start command until the cutover
checklist is fully PASS.