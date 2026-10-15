# Staging test evidence

Record of every verification run performed for the Python backend migration.
Each entry lists the exact command shape, the environment used, and the actual
result. No credentials, hashes, tokens, or customer data appear in this file;
connection strings and secrets were supplied through environment variables in
the sandbox only and are not recorded.

Evidence categories are defined in
[COMPATIBILITY-REPORT.md](COMPATIBILITY-REPORT.md#evidence-categories-used-in-this-report).
Anything not listed here has **not** been performed. Merged code on `master`
is not deployed; production runs on the Node backend.

## Environment descriptions

- **Sandbox SQLite scratch databases**: fresh files under an external scratch
  path (`/tmp`), created and deleted per run. Selected through
  `PYTHON_TEST_DATABASE_URL` (the documented override); conftest applies it to
  `DATABASE_URL` before any test module is imported.
- **Disposable PostgreSQL 15.19** (categories 1–2 evidence only): a
  PostgreSQL 15.19 server in this workspace with a dedicated test role
  (`mcx_pytest`), a freshly created empty database (`mcx_pytest_disposable`),
  and TLS with a workspace CA (`sslmode=verify-full`). Identity was confirmed
  with `SELECT current_database(), current_user` over a local socket before
  every use. It is not a hosting-provider staging environment, holds no
  production or personal data, and is disposable.
- **Throwaway duplicate-demo PostgreSQL database**: a second disposable
  database (`mcx_pytest_dupdemo`) created to demonstrate migration 003
  failure semantics, seeded only with synthetic users and synthetic
  non-personal hash strings, and dropped immediately after the demonstration.

## 2026-10-15 runs (this branch, `completion/python-backend-staging-readiness`)

### Python compilation and dependency consistency

- `python3 -m compileall -q app tests` — passed.
- `python3 -m pip check` — passed (no broken dependency requirements).
- Root `npm run lint` — 0 errors (7 pre-existing warnings in `apps/web`,
  present on master before this work and untouched by it).

### Local automated tests (category 1)

```sh
PYTHON_TEST_DATABASE_URL="sqlite:////<external-scratch>/staging-readiness-full.db" \
  python3 -m pytest tests/ -q
```

Result: **109 passed, 7 skipped, 0 failed**. The 7 skips are the
PostgreSQL-gated concurrency/schema tests. Provider calls (Paystack, WiseSub,
Brevo) are mocked; no live provider was contacted.

New regression tests added in this run:

- `python -m app.schema_check` exits 0 with `"compatible": true` on a current
  schema and exits 1 with non-sensitive name-only diagnostics on an
  incompatible schema (missing table demonstrated).
- A request presenting only a legacy `connect.sid` cookie is anonymous
  (Express sessions never transfer to Python), and logout clears both the
  `melodexs_session` and `connect.sid` cookie names.

### Test-hygiene fix found during this run

`tests/test_api.py` and `tests/test_compatibility.py` overrode `DATABASE_URL`
at module import to an in-repo `tests/test.db`, silently bypassing the
conftest scratch-database configuration for the whole suite. The overrides
were removed; the scratch file `tests/test.db` (empty, untracked) was deleted.
The suite now genuinely runs against `PYTHON_TEST_DATABASE_URL`.

### Disposable-PostgreSQL tests (category 2)

Gate configuration (values via protected sandbox environment; not recorded):

```sh
RUN_POSTGRES_INTEGRATION=1 \
POSTGRES_TEST_DATABASE_VERIFIED=YES \
POSTGRES_TEST_DATABASE_URL="$DISPOSABLE_TEST_POSTGRES_URL"   # sslmode=verify-full
POSTGRES_TEST_EXPECTED_HOST=localhost \
POSTGRES_TEST_EXPECTED_DATABASE=mcx_pytest_disposable \
POSTGRES_TEST_EXPECTED_USERNAME=mcx_pytest \
  python3 -m pytest tests/test_postgres_concurrency.py -q
```

Result: **7 passed, 0 failed** — concurrent reset-token redemption consumed
exactly once, concurrent duplicate reset-token hash creation rejected by the
unique index, token expiry during row-lock wait rejected, concurrent
rate-limit boundary held, concurrent Paystack credit and duplicate purchase
requests idempotent, migrated schema passes the checker, and the checker
detects absent or wrongly redefined reset-token indexes. Gate fail-closed
behavior (hostname mismatch, target equal to the application `DATABASE_URL`)
was verified in the prior run recorded on `master` and re-verified via the
gate tests in the default suite.

### Migration safety on disposable databases (category 2)

All against `mcx_pytest_disposable` (identity confirmed first), except the
duplicate demo:

- `psql -f diagnostics/reset_token_unique_preflight.sql` —
  **0 duplicate hash groups / 0 rows** (aggregate counts only; the diagnostic
  never prints hashes or user IDs).
- Migrations 001, 002, 003 re-applied — all idempotent no-ops
  (`IF NOT EXISTS` notices only; no data changed).
- Migration 003 on the throwaway `mcx_pytest_dupdemo` database seeded with two
  users sharing one synthetic hash: preflight reported **1 group / 2 rows**
  (aggregates only); the migration **failed** with `could not create unique
  index` (PostgreSQL prints the offending key value in this error; the demo
  value was synthetic); post-failure counts confirmed all rows unchanged.
  The throwaway database was then dropped.
- `python -m app.schema_check` on the migrated disposable database — exit 0,
  `"compatible": true`, dialect postgresql, 6 tables clean.
- `python -m app.schema_check` on the unmigrated `dupdemo` database (base
  schema only, pre-003) — **exit 1**, incompatible, with name-only diagnostics
  (`users: missing_indexes: uq_users_reset_token_hash`, etc.).

### Node smoke test (category 3; also the entire Node suite, category 4)

```sh
DB_PATH=<external-scratch>/node-smoke.db \
DATABASE_URL="postgresql://...@localhost:5432/mcx_pytest_disposable?sslmode=<mode>" \
  node test/api-smoke.test.js
```

Result: **passed** (2026-10-15). The Node API started against the disposable
PostgreSQL session store, `/api/status` returned success JSON, and
`/index.html` served with the MELODEXS CONNECT branding. `apps/api/test/`
contains no other automated test; `apps/api/scripts/*` are manual provider
scripts and were not run. This is a smoke test, not a Node/Python contract
comparison (category 5, not run).

## 2026-10-15 (later run, total-replacement branch)

Re-run on branch `completion/python-backend-total-replacement` (master now
contains the merged PR #4):

- `bash scripts/test-api-python.sh` (fresh external scratch SQLite, default
  suite): **112 passed, 7 skipped, 0 failed** — the 3 added tests are the
  frontend-contract tests below.
- New `tests/test_frontend_contract.py`: every `/api/` literal in `apps/web`
  matches a registered Python route (30 routes total; FastAPI's included
  routers resolve lazily, so the test traverses the `_IncludedRouter`
  wrapper's `original_router`); Python routes unused by the frontend are
  exactly the server-only allow-list; `apps/web/api.js` keeps exactly one
  cutover switch and one production URL constant, never localhost.
- `apps/web/api.js`: removed a duplicated `window.MELODEXS_CATEGORIZED_CATALOG`
  assignment (verified by a regression assertion), centralized the API origin
  resolution, added the localhost guard, and added the documented
  `API_TARGET_IS_PYTHON` cutover switch (default false — Node behavior
  unchanged).
- Root `package.json`: `start`/`dev`/`api` now start the Python API;
  `start:node`/`dev:node`/`api:node` keep the Node rollback entry points;
  `test:api-python` runs the suite via `scripts/test-api-python.sh` (external
  scratch SQLite only).
- New `apps/api-python/env.example` (no real values) documenting every
  Python API environment variable with startup-validation notes.

## 2026-10-15 — local Render-style deployment simulation (NOT staging)

Performed in the workspace against a fresh disposable PostgreSQL 15.19
database (`mcx_render_sim`, TLS verify-full, sandbox-only; isolated from
production by hostname/database/user checks). This is deployment-simulation
evidence only — no real staging environment exists yet, and none of this
constitutes a staging walkthrough.

- Base schema + migrations 001/002/003 applied cleanly to a fresh database.
- Startup safety: `NODE_ENV=production` with missing `DATABASE_URL`, missing
  or short `SESSION_SECRET`, or non-live `WISESUB_ENVIRONMENT` each refuse
  to start (fail-fast, no server, no DB write).
- `npm start` (root startup script, production config) boots the API;
  `/api/status` returns 200 OK; the static home page and `/api/data-plans`
  serve correctly; registration writes via identity-generated ids.
- Login sets `melodexs_session` with `HttpOnly; Secure; SameSite=none` in
  production mode; the cookie authenticates `/api/user/{id}`; a disallowed
  Origin receives 403 (cross-origin check verified).
- Startup + access logs contain no secrets (0 matches for the session
  secret, provider keys, Paystack key, and test password in the log).
- Rollback cross-read: the Node `pg` driver reads a Python-written user row
  and sees all migration-002 columns — application rollback to Node does not
  require schema rollback (additive columns only).
- Found and fixed: the `npm start` command lacked `--proxy-headers`, so behind
  Render's proxy rate limiting would bucket all users as one client. Fix in
  PR #6 (`fix/staging-proxy-headers`) with a `FORWARDED_ALLOW_IPS` knob.

## Not performed on 2026-10-15 (as of the local runs above)

- Side-by-side Node/Python runtime comparison (category 5) — **not run**.
- Staging browser walkthrough, hosting-provider staging, provider sandbox
  validation, live-config checks (category 6) — **not run at that point;
  blocked on staging access** (see [CUTOVER-CHECKLIST.md](CUTOVER-CHECKLIST.md)).
- Production deployment, production database contact, live purchases, real
  customer emails (category 7 and live actions) — **not performed and not
  authorized**.

The staging items were subsequently unblocked and performed later on
2026-10-15 — see "Render staging deployment, walkthrough, and
re-verification (category 6)" below. Categories 5 and 7 remain not run.

## 2026-10-15 (late run) — Render staging deployment, walkthrough, and re-verification (category 6)

A real hosting-provider staging environment now exists on Render (free tier,
Oregon region), API-provisioned. **Production was not touched by any of this.**

Environment:

- **Python staging API**: `https://melodexs-connect-api-staging.onrender.com`
  (Render service `melodexs-connect-api-staging`), branch
  `fix/staging-proxy-headers` at commit `f556180`, whose content is identical
  to master at merge commit `87c1327` (PR #6, merged). Start command is the
  plain Uvicorn form (see findings below); health check path `/api/status`.
- **Staging frontend**: `https://melodexs-connect-staging.onrender.com`
  (Render static site, branch `staging/frontend-config`), with every
  `api-base-url` meta tag pointing at the staging API.
- **Staging PostgreSQL**: `melodexs-connect-staging-db` (free tier, expires
  2026-11-14), reached over Render's internal network. It is a fresh,
  empty database provisioned for staging — **not** a copy of production
  data. Base schema and migrations 001/002/003 were applied before first
  boot.
- **Production (verified untouched, category 7 read-only check):** the
  production service still runs Node (`rootDir: apps/api`,
  `npm start` → `node src/server.js`); the Python-only route
  `/api/data-categories` returns an Express 404 on production; production
  env keys and settings are unchanged; no production deploy, env change, or
  database contact was made by the staging work. Production auto-deployed
  twice on 2026-10-15 **because the owner merged PRs #5 and #6 to master**
  (autoDeploy on commit), not because of any staging action. That merge
  changed the *root* `package.json` `start` to the Python command, but the
  production service has `rootDir: apps/api`, so production still boots
  Node from the workspace `apps/api/package.json`. This is a latent risk to
  record, not a change: if the production service's root directory were
  ever set to the repo root, `npm start` would try to boot Python, whose
  startup schema check would hard-fail against the unmigrated production
  database (crash-loop, not silent divergence). Do not change the
  production root directory or start command until the cutover checklist is
  fully PASS.

Deployment findings (Render free tier), each evidenced by deploy logs:

- **Pre-deploy commands and one-off jobs cannot run on the free tier**
  (log line: "Predeploy command not run. Commands can only run on paid
  instance types"). The base schema and migrations 001/002/003 were
  therefore applied as an idempotent one-shot via a **temporary** start
  command, after which the normal Uvicorn start command was restored.
  Migrations were never wired into application startup.
- **Shell default expansion in the start command fails on Render**:
  `--forwarded-allow-ips ${FORWARDED_ALLOW_IPS:-127.0.0.1}` broke the
  deploy (Uvicorn received a glob of the repo root). The working start
  command is the plain form `python3 -m uvicorn app.main:app --app-dir
  apps/api-python --host 0.0.0.0 --port $PORT --proxy-headers`; the
  `FORWARDED_ALLOW_IPS` knob is set as a Render environment variable
  instead, which Uvicorn reads natively.
- **`FORWARDED_ALLOW_IPS` is set to `*` on staging** (trust Render's
  managed proxy, whose IPs are not enumerable in the docs we may rely on).
  The service port is only reachable through Render's edge, so this is
  acceptable for staging rate-limit attribution; the owner can tighten it
  to Render's published proxy ranges before any production use.
- **The Render API's env-var `PUT` endpoint replaces the full variable
  set**, not a partial update: an unintended wipe of the staging service's
  variables caused two failed deploys (caught by startup validation —
  missing `WISESUB_ENVIRONMENT` refused to boot; an external database URL
  failed SSL). All variables were restored from the API's own
  connection-info endpoint. A fresh staging `SESSION_SECRET` was issued, so
  **all staging sessions created before 2026-10-15 23:15 UTC are
  invalidated**; users must log in again. No other data was affected.
- **A pre-deploy migration hook remains configured on the staging service**
  (a one-shot migration script set while working around the free-tier
  limitation). It never executes on the free tier, but the Render API
  cannot clear it; **owner action: remove the Pre-Deploy Command in the
  staging service dashboard**, since a plan upgrade would make it run
  migrations automatically on every deploy, which MIGRATION-STAGING.md
  forbids.
- **Log retention on the free tier is very short** (minutes under the
  health-check ping volume), so the original migration-run log lines are no
  longer retrievable. Idempotency evidence therefore rests on: the
  recorded double-run on the disposable PostgreSQL database (below), the
  `IF NOT EXISTS` construction of all three migrations, and the fact that
  every staging boot runs the startup schema check, which hard-fails if any
  migration 001/002/003 object is missing — and staging boots.

### Staging verification actually performed (2026-10-15)

API-level (curl), against the final live deploy
(`dep-db8lrnm89jmc73btpas0`):

- `GET /api/status` → 200 `{"success":true,...}`.
- Registration → success; the new user received a **database-generated
  id** (identity-backed primary keys confirmed on staging PostgreSQL).
  A malformed Nigerian phone number was correctly rejected first
  (validation active).
- Login → success, `melodexs_session` cookie set; authenticated
  `GET /api/user/{id}` → 200 with the account's fields.
- CORS preflight from the staging frontend origin → 204 allowed; from an
  unknown origin → 403 denied.
- `GET /api/admin/stats` unauthenticated → 401 (admin gate intact).
- `GET /api/data-plans?network=mtn` and
  `GET /api/data-categories?network=mtn` → success with **empty lists**:
  the staging database has no plans because the catalog is populated by a
  WiseSub sync, which requires provider credentials not configured on
  staging (see blockers). Empty is the correct fresh-database behavior.

Browser walkthrough (earlier on 2026-10-15, against the same environment
before the session-secret rotation): register → purchase-PIN creation →
logout → login → dashboard loads (name, email, phone, balance, PIN state)
from the staging database. After the secret rotation these accounts must
re-login; the flows themselves were re-verified at the API level above.

Not performed (staging): Paystack sandbox funding/webhook, WiseSub
sync/purchase flows, Brevo test email (no provider test credentials are
configured on staging — owner action), Node smoke test against the staging
database (rollback cross-check), side-by-side Node/Python route matrix,
load/rate-limit behavior, and any operation against production or
production data.
