# Render Deployment Guide — Python API (staging)

Exact steps for creating the **Python staging web service** on Render. This
guide was prepared from the repository's actual structure on 2026-10-15.
The production Node.js API service and the production frontend service are
NOT touched by anything here.

## Existing services (from repository configuration)

| Service | URL | Runtime | Status |
|---|---|---|---|
| Production API | `https://melodexs-connect-api.onrender.com` | Node.js (`apps/api/`) | UNCHANGED — keep running |
| Production frontend | `https://melodexs-connect.onrender.com` | Render static site | UNCHANGED — keep running |
| Python staging API | (to be created below) | Python 3.11 | TO CREATE |
| Staging frontend | (to be created below) | Render static site | TO CREATE |
| Staging PostgreSQL | (to be created below) | Render PostgreSQL | TO CREATE |

Verify these in the Render dashboard before starting; the URLs above come
from the repository's configuration constants and may have been renamed.

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
