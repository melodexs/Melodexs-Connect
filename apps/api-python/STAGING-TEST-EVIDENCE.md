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

## Not performed on 2026-10-15

- Side-by-side Node/Python runtime comparison (category 5) — **not run**.
- Staging browser walkthrough, hosting-provider staging, provider sandbox
  validation, live-config checks (category 6) — **not run; blocked on staging
  access** (see [CUTOVER-CHECKLIST.md](CUTOVER-CHECKLIST.md)).
- Production deployment, production database contact, live purchases, real
  customer emails (category 7 and live actions) — **not performed and not
  authorized**.
