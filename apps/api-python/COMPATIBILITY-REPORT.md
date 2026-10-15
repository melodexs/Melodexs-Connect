# Python API compatibility and migration audit

Audit updated 2026-10-15 from repository source, mocked local tests, and the
disposable-PostgreSQL verification run recorded in [STAGING-TEST-EVIDENCE.md](STAGING-TEST-EVIDENCE.md).
The active production runtime remains `apps/api/`; no production database, live
provider, or production setting was accessed. WiseSub capabilities below are
based on its [published service/package docs](https://www.wisesub.com.ng/docs/services),
[purchase docs](https://www.wisesub.com.ng/docs/purchases), and
[transaction status docs](https://www.wisesub.com.ng/docs/transactions).

### Evidence categories used in this report

These are **not** interchangeable, and each claim below names its category:

1. **Local automated tests** — the Python suite on an isolated scratch
   SQLite database (no repo or production files).
2. **Disposable-PostgreSQL tests** — sandbox PostgreSQL 15.19 with a
   dedicated test role, TLS `sslmode=verify-full`, and the explicit opt-in
   gate. Evidence for PostgreSQL semantics only; not a hosting-provider
   environment.
3. **Node smoke test** — `apps/api/test/api-smoke.test.js`, the only
   automated Node test in the repository. It starts the Node API against a
   test database and checks `/api/status` and static page serving. It is a
   smoke test, not a contract comparison.
4. **Full Node API suite** — no additional Node tests exist beyond the
   smoke test, so "running the Node suite" means running that smoke test.
5. **Side-by-side runtime comparison** — exercising Node and Python
   simultaneously against the same isolated data. **Not run.**
6. **Staging browser verification** — walkthrough on a deployed staging
   environment. **Not run; blocked on staging access.**
7. **Production deployment** — **not performed** and not authorized by this
   work. Code merged to `master` is deployed only through an explicit,
   separate hosting action; merging is not deployment.

## API compatibility

The Python implementation covers the currently used Node routes and frontend
contract for status/session, register/login/logout/password reset, profile and
transaction history, purchase PINs, public/admin plan reads and admin plan
edits, airtime/data purchases, admin reporting, Paystack initialize/verify, and
Paystack webhooks. This work adds `POST /api/logout` to both Python and the
modular Node router because the frontend expects it. The Node route destroys
its Express session and clears `connect.sid`; the Node smoke test (category 3)
passed against the disposable PostgreSQL on 2026-10-15, but no side-by-side
runtime comparison (category 5) has been run. Python also adds category,
synchronization, pending purchase, and reconciliation endpoints required by the
new plan/purchase flow.

| Area | Python behavior | Remaining comparison / limits |
|---|---|---|
| Session/auth | Registration logs in; login/logout, reset, cookie sessions, and ownership/admin checks implemented. Regression tests prove a request presenting only a legacy `connect.sid` is anonymous and that logout clears both cookie names. | Node uses signed `connect.sid`; Python uses `melodexs_session`. Existing sessions do not transfer; all users re-login at cutover. Route error/cookie/CORS comparison needs staging. |
| User/PIN/history | Profile, history, set/change/verify PIN. | Source-level paths/fields reviewed; full response/error parity needs Node runtime. |
| Data catalog | Admin sync/list/edit; public categories and filtered plans; only admin-enabled, provider-available, categorized rows are purchasable. | Customer frontend now uses new Python endpoints; current Node has not been extended for those endpoints. Do not publish the changed frontend against Node without staging compatibility work or the Python API. |
| Admin catalog | Free-form category assignment, enable/disable, fixed price override or calculated price, manual sync. | Browser walkthrough not run. Category assignment is per plan; there is no separate category-definition table. |
| Purchases | Current plan and expected price checked again under plan row lock; wallet debit and pending transaction share a DB transaction. Timeout stays pending. | Provider status/idempotency semantics and PostgreSQL locks require staging. No retry is sent automatically. |
| Paystack | Server verification, raw HMAC webhook, pending-only transaction transition and one credit. | Duplicate protection is source-reviewed and mocked on SQLite; concurrent PostgreSQL workers have not been tested. |
| CORS/cookies | Credentialed origin allow-list; secure HttpOnly cookie in production; mutating cross-origin requests origin checked. | Render HTTPS, preflight, CSRF protections, and actual origin configuration need staging. |

Node endpoint-specific auth/status/response comparisons were reviewed from
`apps/api/src/routes`, controllers, middleware, `apps/web/api.js`, and the page
fetch calls. A side-by-side runtime comparison (category 5) remains outstanding:
the Node smoke test (category 3) passed against the disposable PostgreSQL test
database on 2026-10-15, but that only proves the Node service starts and serves
`/api/status`; it does not compare route responses with Python. The Python
logout clears its own session and the old cookie name, but does not interpret
an Express session: `connect.sid` values never authenticate to Python (covered
by an explicit regression test), so every user must re-login at cutover.

### Route-by-route coverage

| Method and path | Auth | Request/response contract reviewed |
|---|---|---|
| `GET /api/status` | Public | Success health JSON. |
| `GET /api/session` | Optional cookie | Logged-in flag, public user and PIN flag; no-cache headers. |
| `POST /api/register` | Public | name/email/phone/password; creates account and session; returns user. |
| `POST /api/login` | Public | email/password; returns user and sets session cookie. |
| `POST /api/logout` | Cookie if present | Destroys session, clears cookie; added to Node in this work. |
| `POST /api/forgot-password` | Public | email; generic success response and mocked Brevo send. |
| `POST /api/reset-password` | Public reset token | token/newPassword; consumes token and invalidates sessions. |
| `GET /api/user/:id` | User/admin ownership | Own profile fields and PIN flag; validates ID. |
| `GET /api/transactions/:userId` | User/admin ownership | Transaction list ordered newest first. |
| `GET /api/data-plans` | Public | plan/network/category/selling price/size/validity, filtered by optional network/category. |
| `GET /api/data-categories?network=...` | Public | Eligible nonempty category names/count for selected network; Python addition. |
| `POST /api/purchase-data` | User + PIN | network/plan/phone/pin/expectedPrice/requestId; authoritative price and plan recheck; result or pending. |
| `POST /api/purchase-airtime` | User + PIN | network/phone/amount/pin/requestId; pending/success/refund contract. |
| `POST /api/purchase-pin/set` | User | pin; confirmation JSON. |
| `POST /api/purchase-pin/change` | User | currentPin/newPin; confirmation JSON. |
| `POST /api/purchase-pin/verify` | User | pin; confirmation JSON. |
| `POST /api/fund-wallet` | User | amount; server initializes Paystack and returns checkout details. |
| `POST /api/fund-wallet/verify` | User | reference; server verification and idempotent credit. |
| `POST /api/paystack/webhook` | HMAC signature | raw JSON body; signed success events only; no session required. |
| `GET /api/admin/stats`, `/users`, `/transactions` | Admin | Existing summary, user, and transaction response collections. |
| `GET/POST/PATCH /api/admin/data-plans[/:id]` | Admin | Plan list/create/update; Python listing includes inactive/unavailable rows and override/category controls. |
| `POST /api/admin/data-plans/synchronize`, `GET /api/admin/data-plans/synchronization` | Admin | Provider catalog refresh and latest run/error summary; Python additions. |
| `GET /api/admin/purchases/pending`, `POST /api/admin/purchases/reconcile`, `POST /api/admin/purchases/:id/resolve` | Admin | Inspect pending, query provider status, or explicitly record a human resolution; Python additions. |

The modular Node API does not yet expose the Python category/sync/reconciliation
routes. `api.js` resolves the API origin in one place — the HTML
`api-base-url` meta tag, then the `PRODUCTION_API_URL` constant, then the page
origin for local development — and a hosted page can never resolve to
localhost. The single `API_TARGET_IS_PYTHON` switch (false while Node serves
production) enables the Python-only category and reconciliation UI and is
flipped only at the approved cutover; see CUTOVER-CHECKLIST.md step 7. A new
automated frontend-contract test (`tests/test_frontend_contract.py`) scans
every `apps/web` page for `/api/` literals and fails if any frontend call has
no matching Python route (or any Python route is neither used by the frontend
nor on the explicit server-only allow-list: `/api/status`,
`/api/purchase-pin/verify`, `/api/paystack/webhook`). Route parity as of
2026-10-15: 30 registered Python routes (22 core + 8 admin) covering all 26
distinct frontend calls; Node exposes 24.

## WiseSub catalog facts and sync design

The existing integration requests `GET /services` and
`GET /packages?service_type=data&provider_code=...`. Published examples show
data networks with provider codes and package fields `package_code`,
`package_name`, `price` (and optional commission). The docs do **not** show
category, description, validity, or availability fields. The implementation
does not fabricate provider category data; it extracts size/validity only from
the package name for display and requires admins to classify a plan before it
appears to customers.

`POST /api/admin/data-plans/synchronize` is admin-only and manual. It validates
all packages for each successful network response, keys plans by WiseSub
provider/network/package code, and upserts under a PostgreSQL advisory lock plus
a unique provider-identity index. It keeps disabled state, category, and fixed
price override; updates provider cost; recalculates the current customer price
only when no fixed override exists; and marks packages missing from a valid
snapshot unavailable without deleting rows. A failed/malformed network response
does not deactivate old plans. Sync attempts store outcome and error details.
No scheduler is configured because deployment scheduling capability has not
been established.

The existing Node sync rule is provider cost + `CHEAPDATA_MARKUP_PERCENT`
(default 2%), rounded **up** to a whole naira. Thus ₦3,000 becomes ₦3,060 under
the source rule. An admin fixed override remains fixed through provider changes;
clearing it resumes the configured calculation. Browser price is advisory:
the Python API re-reads plan price under row lock and rejects a stale expected
price before debiting.

## Purchase and payment integrity

Data/airtime debits and pending transactions are atomic. Provider references
follow WiseSub's documented Africa/Lagos `YYYYMMDDHHII` plus alphanumeric
suffix. PostgreSQL serializes wallet modifications with row locks and a
conditional balance decrement.
Purchase request IDs have a unique per-user index, and a matching unresolved
network/product/phone purchase is also blocked. Only a pending transaction can
be marked successful or failed/refunded. Provider HTTP errors and `success:false`
responses remain pending because the published docs do not say which errors are
final. Reconciliation uses WiseSub's
documented `GET /status?reference=...` endpoint; successful states can be
finalized. The docs show a successful status example but do not document all
terminal failures or confirm timeout lookup with the caller-supplied reference.
Therefore a returned `failed` status does not auto-refund by default. Enable
`WISESUB_FAILURE_STATUS_CONFIRMED=true` only after staging confirms the
provider's terminal failure semantics. Otherwise admins inspect evidence and
use an explicit audited manual resolution. Unknown or timeout statuses stay
pending. This flow is mocked only; no vending request was made.

Paystack funding verifies reference, amount, currency, metadata and signature;
wallet credit and pending-to-success state update share a transaction. Duplicate
webhooks are protected by row lock/status transition. SQLite tests do not
establish concurrent PostgreSQL behavior.

## PostgreSQL and migrations

Node migrations/runtime use PostgreSQL (`DATABASE_URL`) with users,
`data_plans`, transactions and sessions. The inspected old SQLite-to-Postgres
migration declares integer IDs without defaults even though runtime inserts
omit IDs; the deployed schema's actual sequences/identity columns are unknown.
No production or staging PostgreSQL was available to inspect. The Node migration
and runtime also define/use `is_admin` and `active`, while migration 002 adds
`provider_available`, as integer flags compared against `0`/`1`. PostgreSQL
`BOOLEAN` is incompatible with those query expressions. The Python schema
checker now rejects BOOLEAN for these fields rather than accepting a schema the
queries cannot use.

Python production startup performs a read-only schema check and refuses an
incompatible schema. It compares required index definitions as well as index
names. Additive migrations are:

- `migrations/001_api_rate_limits.sql`
- `migrations/002_dynamic_data_catalog_and_reconciliation.sql`
- `migrations/003_unique_password_reset_tokens.sql` (run
  `diagnostics/reset_token_unique_preflight.sql` first; it creates the partial
  unique index `uq_users_reset_token_hash` on non-null reset-token hashes)

Migration 002 adds category/availability/override/sync fields and transaction
idempotency/provider-reference fields plus partial unique indexes. Index
creation can fail if old data contains duplicate provider identifiers or
transaction references; check on a staging copy first. It preserves current WiseSub
selling prices as fixed overrides because the old admin UI had no override
flag; admins can clear these individually after review. None of the
migrations has been applied to a production or hosting-provider database.
A schema-check defect found during this run was fixed: the PostgreSQL
constraint-catalog query cross-joined `key_column_usage` with
`constraint_column_usage`, which duplicated multi-column constraint columns
(a genuine `UNIQUE(network,plan)` aggregated as `network,network,plan,plan`)
and made that constraint permanently undetectable, so production startup
would always have refused. Constraints are now collected with correlated
subqueries. The checker has been run against isolated SQLite and against the
disposable PostgreSQL 15.19 test database described below.

## Verification performed

- Local automated tests (category 1): `PYTHON_TEST_DATABASE_URL=<fresh
  scratch SQLite> python -m pytest tests/ -q`: **109 passed, 7 skipped**
  (PostgreSQL-gated concurrency tests); provider calls are mocked. A
  test-hygiene defect found during this run was fixed: `tests/test_api.py`
  and `tests/test_compatibility.py` silently overrode `DATABASE_URL` to an
  in-repo `tests/test.db` at module import, bypassing the conftest scratch
  configuration; the overrides were removed so every test now genuinely runs
  against `PYTHON_TEST_DATABASE_URL`.
- Disposable PostgreSQL 15.19 verification (sandbox only; TLS
  `sslmode=verify-full`, dedicated test role and database, exact
  host/database/username gate enforced, gate proven to fail closed on
  mismatched hostname and on a target matching the application
  `DATABASE_URL`):
  - Base schema provisioned from `tests/postgres_test_schema.sql` (Node
    production DDL with the generated-id difference documented in that file),
    migrations 001, 002, and 003 applied manually.
  - `diagnostics/reset_token_unique_preflight.sql` returned **0 duplicate
    hash groups / 0 rows** before migration 003; the created
    `uq_users_reset_token_hash` matched the reviewed partial-index
    definition.
  - Read-only schema checker: all tables clean after migration 003; it
    correctly reported the index as missing before 003 and reported a
    same-named non-partial redefinition as incompatible.
  - All three migrations re-applied cleanly (idempotent `IF NOT EXISTS`
    no-ops; no data touched). Migration 003 was additionally proven to
    **fail safely on duplicates** on a second throwaway database seeded with
    two synthetic duplicate hashes: the preflight reported only aggregate
    counts (1 group / 2 rows), the migration failed with a unique-index
    violation, and the data was unchanged afterwards. The throwaway database
    was then dropped.
  - `python -m app.schema_check` now **exits nonzero** when the schema does
    not match the reviewed requirements (previously it printed diagnostics
    but always exited 0): exit 1 with non-sensitive name-only diagnostics
    on the unmigrated database, exit 0 with `"compatible": true` on the
    migrated database. FastAPI startup and the CLI share one
    `schema_incompatibilities()` helper.
  - `RUN_POSTGRES_INTEGRATION=1 ... python -m pytest -q
    apps/api-python/tests/test_postgres_concurrency.py`: **7 passed, 0
    failed** — concurrent reset-token redemption consumed once, concurrent
    duplicate hash creation rejected by the unique index, expiry during a
    row-lock wait rejected, concurrent rate-limit boundary held, concurrent
    Paystack credit and duplicate purchase requests idempotent, migrated
    schema passes the checker, and the checker detects absent/redefined
    reset-token indexes.
- `.venv/bin/python -m pip check`: passed.
- `.venv/bin/python -m compileall -q apps/api-python/app apps/api-python/tests`:
  passed.
- `npx cap sync android`: passed.
- `android/gradlew --no-daemon assembleDebug`: passed; produced
  `android/app/build/outputs/apk/debug/app-debug.apk` (8,907,479 bytes).
  Gradle warned about `flatDir` repositories and Android SDK XML version
  mismatch; neither prevented the build. No device/emulator test was run.
- `npm ls --depth=0 --package-lock-only`: passed; lockfile dependencies resolve.
- `git diff --check`: passed at final review.
- Node smoke test (category 3; also the entire Node test suite, see category
  4): run on 2026-10-15 with `DB_PATH=<scratch SQLite>` and the disposable
  PostgreSQL as `DATABASE_URL` — **passed** (Node service started, session
  store initialized, `/api/status` and `/index.html` served). Frontend JS
  runtime checks and the side-by-side runtime comparison (category 5) were
  **not run**.
- Hosting-provider staging (Render or any deployed PostgreSQL), live provider
  behavior, and staging browser verification (category 6): **not verified**;
  no dedicated staging environment exists yet. PostgreSQL itself was verified
  only against the disposable sandbox database described above.
- No real Paystack, WiseSub, or Brevo calls were made. No production
  database was contacted, and no deployment occurred: the Python backend is
  merged on `master` but production traffic still runs on Node.

## Remaining blockers and next steps

1. Create/back up a dedicated PostgreSQL staging database and inspect actual
   primary-key defaults (the disposable test schema intentionally uses
   generated ids, which the Python API requires; a deployed schema created by
   the old Node DDL may declare bare `INTEGER PRIMARY KEY` without a
   default), current duplicate provider identities/transaction references,
   types, constraints, indexes, and transaction/session schema.
2. Apply migrations 001 and 002 in staging; run the read-only Python schema
   checker; test migration rollback only in staging.
3. Run PostgreSQL parallel webhook/verification workers, wallet purchases,
   duplicate request IDs, refunds, and repeated reconciliation tests.
4. With WiseSub test credentials, verify service/package response variants,
   package removal behavior, the exact status lookup reference after a timeout,
   and terminal failed status semantics. No real purchase is needed for initial
   sync/status validation; any sandbox purchase needs explicit operator setup.
5. Run a genuine side-by-side runtime comparison of Node and Python against
   the same isolated staging data (the 2026-10-15 Node smoke test is not a
   substitute), then run the full customer and admin browser walkthrough with
   Python staging per [CUTOVER-CHECKLIST.md](CUTOVER-CHECKLIST.md).
6. Review CSRF/origin protection and test Secure/SameSite cookie behavior across
   the separate frontend/API origins. Plan for user re-login and Node rollback.

Until these gates pass, keep Node serving production traffic and do not call the
Python replacement production-ready.
