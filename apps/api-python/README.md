# MELODEXS CONNECT Python API

This is the recovered FastAPI implementation from the `python-backend-migration`
branch. It covers the existing `/api` route families while the Node API remains
the active production service. Do not switch Render traffic until PostgreSQL
compatibility, payment concurrency, and the session cutover have been verified.

## Local setup

From the repository root, use Python 3.10 or newer:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r apps/api-python/requirements.txt
```

The application reads the root `.env`. Set `DATABASE_URL` to a dedicated local
or test PostgreSQL database to match production. For isolated development,
SQLite is used when no URL is configured. The pytest setup forcibly selects its
own SQLite file and `NODE_ENV=test`, even if shell or `.env` values point
elsewhere. Never use production data for tests. Required credentials remain
server-side; use the root `.env.example` for variable names.

Run locally from the repository root:

```sh
uvicorn app.main:app --app-dir apps/api-python --host 127.0.0.1 --port 3000 --reload
```

Run Python tests with:

```sh
python -m pytest -q apps/api-python/tests
```

Run the existing Node smoke test with `npm test` only after setting
`DATABASE_URL` to a dedicated test PostgreSQL database. The Node test starts
the API and connects to the configured database.

## PostgreSQL and migrations

Production startup requires a PostgreSQL `DATABASE_URL` and a session secret of
at least 32 characters. It performs a read-only schema check and refuses to
start if required columns are missing. It does not create tables or alter
production data. `migrations/001_api_rate_limits.sql` and
`migrations/002_dynamic_data_catalog_and_reconciliation.sql` are additive
migrations. Review and apply them manually in a backed-up staging database
first. Migration 002 adds provider availability, fixed price overrides,
admin-assigned categories, sync history, and purchase idempotency fields/indexes.
Its unique provider-package, transaction-reference, and user/idempotency
indexes can fail if existing rows contain duplicate values; inspect and
resolve those in staging before applying.
Migration 002 preserves every existing WiseSub selling price as a fixed
override because the old admin UI did not distinguish edited prices from
calculated prices. Admins can clear individual overrides after review to resume
automatic markup pricing.
Neither migration has been applied to a PostgreSQL database. The Node API
remains available for rollback.

Run the read-only schema check from the repository root:

```sh
PYTHONPATH=apps/api-python python -m app.schema_check
```

The schema checker compares columns, types, nullability, keys, ID generation,
and required index definitions. It has only been run against isolated SQLite in this
workspace; no deployed PostgreSQL schema was queried. PostgreSQL startup is
read-only and refuses to start when the reviewed schema is absent. `connect.sid`
sessions are not transparently decoded by this service; customers should log in
again after cutover. Python uses an HttpOnly `melodexs_session` cookie, Secure
and SameSite=None in production HTTPS, and deletes both its cookie and old
`connect.sid` on logout. Keep web and API origins separate, preserve the CORS
allow-list, and test preflight/cookie behavior in staging. Mutating cross-origin
requests are origin-checked; a full CSRF review remains part of staging.

## Dynamic data plans and categories

Plan refresh is manual and admin-only:

- `POST /api/admin/data-plans/synchronize` fetches the documented `/services`
  and `/packages?service_type=data&provider_code=...` catalog.
- `GET /api/admin/data-plans/synchronization` reports the latest sync outcome.
- `GET /api/admin/data-plans` lists enabled, disabled, available, and
  unavailable provider plans. The admin page synchronizes, sets selling prices,
  enables/disables plans, and assigns categories.
- Category names are free-form data. Entering a category on a plan introduces
  that category for the network; clearing it keeps the plan hidden until it is
  classified. Unclassified plans never appear in customer choices.
- A fixed selling-price override survives provider price changes. Clearing the
  override returns the plan to provider cost plus `CHEAPDATA_MARKUP_PERCENT`
  (default 2%), rounded up to the next whole naira. This preserves the existing
  Node sync rule: a ₦3,000 provider cost calculates to ₦3,060.
- Customers choose network → category → plan. The browser refreshes current
  catalog data before confirmation; the server rechecks the expected price
  while locking the selected plan and never trusts the submitted amount.

WiseSub's published package response documents `package_code`, `package_name`,
and `price`; it does not document categories or an availability field.
Categories therefore require admin assignment. A plan becomes unavailable only
when absent from a valid successful network snapshot. A failed, timed-out,
duplicate, or malformed response does not deactivate that network's plans. No
scheduled job is configured; manual sync works without a browser job.

## Purchase reconciliation

Wallet debit and pending transaction are committed together. Purchases use a
WiseSub-format server reference: local Africa/Lagos `YYYYMMDDHHII` followed by
an alphanumeric random suffix. Browser request IDs prevent repeat wallet
debits. Duplicate request IDs and a
matching unresolved customer/network/plan/phone request do not debit again.
Timeouts, HTTP errors, and `success:false` provider replies stay pending because
WiseSub docs do not establish which error responses are final. Admins can inspect
`GET /api/admin/purchases/pending`, check status through
`POST /api/admin/purchases/reconcile`, and manually resolve only after checking
provider evidence. WiseSub docs show a successful status example but do not
define every terminal failure state or prove a submitted reference can always
be queried after a timeout. Automatic refund on a `failed` response is disabled
by default; enable `WISESUB_FAILURE_STATUS_CONFIRMED=true` only after staging
confirms the provider's terminal failure semantics. Unknown states remain
pending.

## Current verification and blockers

Last local run: `.venv/bin/python -m pytest -q apps/api-python/tests` passed
**35 tests; one PostgreSQL race test is skipped unless explicitly enabled**.
The default suite mocks Paystack, WiseSub, and Brevo and uses SQLite. It does
not verify PostgreSQL row locking or provider behavior against staging.
`npm test` was not run because the Node smoke test connects to the configured
PostgreSQL database and no dedicated test database was confirmed as a safe
target. See [COMPATIBILITY-REPORT.md](COMPATIBILITY-REPORT.md) for the
source-level endpoint/schema review and remaining cutover blockers.

After applying the reviewed migrations to a dedicated PostgreSQL database whose
name contains `test` or `stage`, run the opt-in concurrent Paystack and purchase
test with:

```sh
RUN_POSTGRES_INTEGRATION=1 TEST_POSTGRES_URL="$DEDICATED_TEST_POSTGRES_URL" \
  .venv/bin/python -m pytest -q apps/api-python/tests/test_postgres_concurrency.py
```

This path performs read-only startup schema validation and requires an already
migrated test/stage database. Never point it at production.

## Render staging configuration

Keep the existing frontend and API as separate services. For a staging API
service, set the build command to:

```sh
pip install -r apps/api-python/requirements.txt
```

Set the start command to:

```sh
uvicorn app.main:app --app-dir apps/api-python --host 0.0.0.0 --port $PORT
```

Configure the same PostgreSQL `DATABASE_URL`, a new 32+ character
`SESSION_SECRET`, existing Paystack/WiseSub/Brevo settings, and the frontend
origin in `CHEAPDATA_PUBLIC_URL`. For a dedicated web staging copy, set the
`api-base-url` meta tag in the HTML pages to the Python API origin; a blank tag
continues using the current Node API URL. The existing frontend already targets
`https://melodexs-connect-api.onrender.com`; do not point it at the web service.
Keep the Node API service running until staging checks pass and a controlled
cutover is explicitly approved. No live service settings are changed here.
