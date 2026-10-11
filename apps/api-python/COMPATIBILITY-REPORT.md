# Python API compatibility and migration audit

Audit updated 2026-10-11 from repository source and mocked local tests. The
active Node runtime remains `apps/api/`; no production database, live provider,
or production setting was accessed. WiseSub capabilities below are based on
its [published service/package docs](https://www.wisesub.com.ng/docs/services),
[purchase docs](https://www.wisesub.com.ng/docs/purchases), and
[transaction status docs](https://www.wisesub.com.ng/docs/transactions).

## API compatibility

The Python implementation covers the currently used Node routes and frontend
contract for status/session, register/login/logout/password reset, profile and
transaction history, purchase PINs, public/admin plan reads and admin plan
edits, airtime/data purchases, admin reporting, Paystack initialize/verify, and
Paystack webhooks. This work adds `POST /api/logout` to both Python and the
modular Node router because the frontend expects it. The Node route destroys
its Express session and clears `connect.sid`; Node runtime tests were not run
because no dedicated PostgreSQL test database was confirmed. Python also adds category,
synchronization, pending purchase, and reconciliation endpoints required by the
new plan/purchase flow.

| Area | Python behavior | Remaining comparison / limits |
|---|---|---|
| Session/auth | Registration logs in; login/logout, reset, cookie sessions, and ownership/admin checks implemented. | Node uses signed `connect.sid`; Python uses `melodexs_session`. Existing sessions do not transfer; all users re-login at cutover. Route error/cookie/CORS comparison needs staging. |
| User/PIN/history | Profile, history, set/change/verify PIN. | Source-level paths/fields reviewed; full response/error parity needs Node runtime. |
| Data catalog | Admin sync/list/edit; public categories and filtered plans; only admin-enabled, provider-available, categorized rows are purchasable. | Customer frontend now uses new Python endpoints; current Node has not been extended for those endpoints. Do not publish the changed frontend against Node without staging compatibility work or the Python API. |
| Admin catalog | Free-form category assignment, enable/disable, fixed price override or calculated price, manual sync. | Browser walkthrough not run. Category assignment is per plan; there is no separate category-definition table. |
| Purchases | Current plan and expected price checked again under plan row lock; wallet debit and pending transaction share a DB transaction. Timeout stays pending. | Provider status/idempotency semantics and PostgreSQL locks require staging. No retry is sent automatically. |
| Paystack | Server verification, raw HMAC webhook, pending-only transaction transition and one credit. | Duplicate protection is source-reviewed and mocked on SQLite; concurrent PostgreSQL workers have not been tested. |
| CORS/cookies | Credentialed origin allow-list; secure HttpOnly cookie in production; mutating cross-origin requests origin checked. | Render HTTPS, preflight, CSRF protections, and actual origin configuration need staging. |

Node endpoint-specific auth/status/response comparisons were reviewed from
`apps/api/src/routes`, controllers, middleware, `apps/web/api.js`, and the page
fetch calls. A side-by-side runtime comparison remains outstanding because the
Node smoke test requires a dedicated PostgreSQL test database; none was
configured as a safe target for this run. The Python logout clears its own
session and the old cookie name, but does not interpret an Express session.

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
routes. `api.js` retains the Node origin by default and supports a staging API
origin through the HTML `api-base-url` meta tag. Keep the meta value blank for
the current Node target; point a separate staging frontend copy to Python only
after applying the staging migrations.

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

Migration 002 adds category/availability/override/sync fields and transaction
idempotency/provider-reference fields plus partial unique indexes. Index
creation can fail if old data contains duplicate provider identifiers or
transaction references; check on a staging copy first. It preserves current WiseSub
selling prices as fixed overrides because the old admin UI had no override
flag; admins can clear these individually after review. Neither migration was
applied.
The checker has only been run against isolated SQLite and is not PostgreSQL
evidence.

## Verification performed

- `.venv/bin/python -m pytest -q apps/api-python/tests`: **35 passed, 1
  PostgreSQL race test skipped**; default provider calls are mocked and tests
  use isolated SQLite.
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
- `npm test`, Node API tests, and frontend JS runtime checks: **not run**;
  the Node smoke test connects to the configured PostgreSQL database, and no
  dedicated test database was confirmed for safe use.
- PostgreSQL schema, migrations, index definitions, locks, concurrent funding/purchase (an opt-in
  race test has been added but not run), and
  browser staging: **not verified**; no dedicated staging database exists.
- No real Paystack, WiseSub, or Brevo calls were made.

## Remaining blockers and next steps

1. Create/back up a dedicated PostgreSQL staging database and inspect actual
   primary-key defaults, current duplicate provider identities/transaction
   references, types,
   constraints, indexes, and transaction/session schema.
2. Apply migrations 001 and 002 in staging; run the read-only Python schema
   checker; test migration rollback only in staging.
3. Run PostgreSQL parallel webhook/verification workers, wallet purchases,
   duplicate request IDs, refunds, and repeated reconciliation tests.
4. With WiseSub test credentials, verify service/package response variants,
   package removal behavior, the exact status lookup reference after a timeout,
   and terminal failed status semantics. No real purchase is needed for initial
   sync/status validation; any sandbox purchase needs explicit operator setup.
5. Run the Node suite against a dedicated test database, compare route
   responses and run a full customer and
   admin browser walkthrough with Python staging.
6. Review CSRF/origin protection and test Secure/SameSite cookie behavior across
   the separate frontend/API origins. Plan for user re-login and Node rollback.

Until these gates pass, keep Node serving production traffic and do not call the
Python replacement production-ready.
