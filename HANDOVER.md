# MELODEXS CONNECT Handover

## 1. Project overview

MELODEXS CONNECT is a Node.js monorepo for a data and airtime reselling platform.
Users register, log in, manage purchase PINs, fund a wallet, and purchase mobile
data or airtime. Administrators can access usage summaries, user records, and
transaction data. The active Node runtime is Express with PostgreSQL through
`DATABASE_URL`; the frontend is a static HTML/CSS interface served by the API.
The SQLite files and `db.js` describe legacy/local maintenance paths, not the
current production database. See the root README for current setup details.

The application is intentionally structured as a monorepo:

- root: workspace tooling, root scripts, lockfile, docs, env config
- `apps/api`: runtime API server, data layer, scripts, tests
- `apps/web`: static frontend pages and styles

## 2. Current architecture

### Core file ownership

- `apps/api/src/server.js`: thin startup file; starts the Express app on the port
  configured by `PORT`.
- `apps/api/src/app.js`: main application definition; configures Express, DB,
  middleware, helper functions, and all route handlers.
- `apps/api/src/config.js`: environment validation and shared config values.
- `apps/api/src/postgres.js`: production PostgreSQL pool using `DATABASE_URL`.
- `apps/api/src/db.js`: legacy SQLite database instance and maintenance helper.
- `apps/api/src/auth.js`: reusable authentication and admin authorization
  middleware.
- `apps/api/scripts/`: database repair scripts, admin scripts, and WiseSub
  provider utilities.
- `apps/api/test/api-smoke.test.js`: isolated smoke test for API health and
  frontend serving.
- `apps/web/`: static customer/admin pages and shared CSS.

### Why the split matters

Before the refactor, the app entry file was handling configuration, database
setup, migrations, middleware, auth, consumer routes, admin routes, wallet code,
and process startup. That made it harder to reason about behavior and easier to
break unrelated logic during a change.

The current split separates responsibilities while preserving behavior:

- config: env and static path management
- database: PostgreSQL runtime access; SQLite lifecycle remains legacy
- auth: session and admin checks
- app: route registration and middleware flow
- server: process startup only

## 3. Repository layout

```text
.
├── apps/
│   ├── api/
│   │   ├── data/
│   │   │   ├── cheapdata.db
│   │   │   ├── cheapdata.db-shm
│   │   │   └── cheapdata.db-wal
│   │   ├── scripts/
│   │   │   ├── add-purchase-pin.js
│   │   │   ├── add-reset-fields.js
│   │   │   ├── fix-database.js
│   │   │   ├── make-admin.js
│   │   │   ├── sync-wisesub.js
│   │   │   ├── test-mtn.js
│   │   │   ├── test-wisesub.js
│   │   │   ├── test-wisesub-plans.js
│   │   │   └── test-wisesub-pricing.js
│   │   ├── src/
│   │   │   ├── app.js
│   │   │   ├── auth.js
│   │   │   ├── config.js
│   │   │   ├── db.js
│   │   │   └── server.js
│   │   ├── test/
│   │   │   └── api-smoke.test.js
│   │   └── package.json
│   └── web/
│       ├── admin.html
│       ├── buy-airtime.html
│       ├── buy-data.html
│       ├── create-pin.html
│       ├── dashboard.html
│       ├── forgot-password.html
│       ├── fund-wallet.html
│       ├── index.html
│       ├── login.html
│       ├── purchase-pin.html
│       ├── register.html
│       ├── reset-password.html
│       ├── styles.css
│       ├── wallet.html
│       └── package.json
├── .env
├── .env.example
├── .gitignore
├── README.md
├── HANDOVER.md
├── eslint.config.js
├── package.json
├── package-lock.json
└── .git/
```

## 4. Local environment setup

### Requirements

- Node.js 18+
- npm

### Install

From the repo root:

```bash
npm install
```

### Environment file

Use `.env.example` as the template. The active runtime file is `.env` and must
stay local. Do not commit it.

Required variables include:

- `PORT`
- `NODE_ENV`
- `SESSION_SECRET`
- `PAYSTACK_SECRET_KEY`
- `DATABASE_URL` (PostgreSQL runtime and smoke-test database)
- `WISESUB_BASE_URL`
- `WISESUB_API_KEY`
- `WISESUB_API_SECRET`
- `WISESUB_ENVIRONMENT`
- `CHEAPDATA_MARKUP_PERCENT`
- `DB_PATH` (legacy SQLite maintenance scripts only)

Do not place real secret values in docs, scripts, or commits.

### Legacy SQLite database path

The default app database path is:

```text
./apps/api/data/cheapdata.db
```

This path is used by legacy SQLite helpers only. The active API requires
`DATABASE_URL` and connects to PostgreSQL.

## 5. Developer commands

From the repo root:

```bash
npm run dev
npm start
npm test
npm run lint
```

From the API workspace directly:

```bash
cd apps/api
npm run dev
npm start
npm test
npm run db:fix
npm run db:reset-fields
npm run db:purchase-pin
npm run make-admin
npm run wise:sync
npm run wise:test
npm run wise:test-mtn
npm run wise:test-plans
npm run wise:test-pricing
```

## 6. Runtime behavior and API surface

### Auth flows

- `POST /api/register`
- `POST /api/login`
- `POST /api/logout`
- `POST /api/forgot-password`
- `POST /api/reset-password`
- `POST /api/purchase-pin/set`
- `POST /api/purchase-pin/change`
- `POST /api/purchase-pin/verify`

These routes manage account creation, password recovery, purchase PIN setup, and
session-based access control. The current work adds `/api/logout` to the modular
Node router and calls it from the admin, dashboard, and PIN pages. The Python
service also supports it. Node runtime tests could not run in this environment.

### Wallet and funding

- `POST /api/fund-wallet` — Paystack wallet funding initialization
- `POST /api/fund-wallet/verify` — server-side Paystack verification
- `POST /api/paystack/webhook` — signed Paystack webhook

Wallet funding uses Paystack and expects `PAYSTACK_SECRET_KEY` to be configured.
Automated tests must mock Paystack and must never submit real payments.

### Purchases

- `POST /api/purchase-data`
- `POST /api/purchase-airtime`

These endpoints validate the authenticated user, check balance, verify purchase
PIN when required, and record transaction history.

### User and admin data

- `GET /api/user/:id`
- `GET /api/transactions/:userId`
- `GET /api/admin/stats`
- `GET /api/admin/users`
- `GET /api/admin/transactions`

The admin endpoints require a valid admin session via `requireAdmin`.

### Health

- `GET /api/status`

This should return a successful JSON response when the API is running.

## 7. Database and migration status

The active Node API uses PostgreSQL through `DATABASE_URL`. SQLite files and
`apps/api/src/db.js` are legacy/local maintenance paths, not the live API's
database. Python uses an isolated SQLite database only for local tests;
production startup performs a read-only PostgreSQL schema check and never
creates or changes production tables.

Python migrations are manual and additive:

- `apps/api-python/migrations/001_api_rate_limits.sql`
- `apps/api-python/migrations/002_dynamic_data_catalog_and_reconciliation.sql`

Review and apply them only to a backed-up staging database first. Migration 002
adds catalog category/availability/price override fields, sync-run records, and
purchase idempotency/provider references. Check for duplicate provider package
identifiers and transaction references before creating unique indexes. It treats current WiseSub selling
prices as fixed overrides because the old admin UI had no override marker;
admins can clear individual values after review. Neither migration has been
applied to PostgreSQL. The Node API remains available for rollback.

## 8. Provider integration notes

### Paystack

Wallet funding initializes a Paystack transaction and expects a valid secret key.
The app validates the amount range, creates a transaction reference, and returns
Paystack authorization details to the frontend.

### WiseSub

Provider data and pricing sync tools live in `apps/api/scripts/` and are used to:

- inspect available plans
- test connection health
- sync data package metadata into the app database
- validate provider pricing

The Node utility sync remains available. Python adds a manual admin-only sync
and records run outcomes. WiseSub's published catalog lists `package_code`,
`package_name`, and `price`, with no category field; plans must be classified by
an admin before customers see them. See `apps/api-python/README.md` for pricing
and reconciliation rules.

## 9. Testing and linting

### Smoke test

The project includes a lightweight smoke test at:

- `apps/api/test/api-smoke.test.js`

This test connects to configured PostgreSQL `DATABASE_URL`. Use a dedicated
test database, never production. It verifies:

- `/api/status` responds successfully
- static frontend assets are being served
- the app can boot without the production database or app startup issues

### Linting

The repository uses ESLint with a shared config in `eslint.config.js`.

Run:

```bash
npm run lint
```

The configured lint rules help catch undefined variables, duplicate identifiers,
invalid control flow, and obvious code quality problems.

## 10. Current known risks and TODOs

- `SESSION_SECRET` must be configured in production. In development, the app logs
  a warning and falls back to an insecure value.
- `/api/test-fund` is a development-only route and should not be active in a
  production deployment.
- Paystack wallet funding is only safe when the full verification flow is tested
  in the target environment.
- WiseSub scripts need valid credentials and network access; they should not be
  used casually in a production environment without review.
- The web frontend is static and served directly. It is not a framework-based
  app, so if richer state management or a build pipeline is needed later, the
  front-end architecture will need a separate decision.
- Python route tests cover auth, purchase PINs, mocked Paystack/WiseSub/Brevo,
  catalog synchronization/filtering, idempotency, and reconciliation. They use
  SQLite and do not prove PostgreSQL row-lock behavior.

## 11. Verification status

On 2026-10-10, Python tests passed 32 cases with one PostgreSQL-only race test
skipped, Python compilation and dependency checks passed, and `git diff --check`
passed. Node/npm and PostgreSQL client
tools plus a dedicated staging database are unavailable in this workspace, so
Node tests, PostgreSQL schema/concurrency checks, and browser staging have not
been verified. No live provider was called.

## 12. Handover notes

If a teammate takes this work over, the first things to inspect are:

1. `.env` values for secrets and provider credentials
2. `apps/api/src/config.js` and `DB_PATH` configuration
3. database state under `apps/api/data/`
4. Paystack and WiseSub environment-specific configuration
5. admin route access and session handling
6. wallet funding and purchase PIN validation flows

The most important ownership boundaries are:

- `app.js` = API wiring
- `server.js` = launcher
- `db.js` = data layer
- `auth.js` = auth policy
- `config.js` = env config
- `scripts/` = operations and provider utilities
- `web/` = frontend UI

This split is now much easier to maintain and safer for future work than the
single monolithic server file.
## 13. Latest upgrade in this package

The current package adds the missing server-side Paystack wallet crediting flow:

- `/api/fund-wallet` initializes a Paystack payment and records it as `pending`.
- `/api/fund-wallet/verify` verifies the reference directly with Paystack.
- The wallet is credited only after the server confirms `success`, NGN currency, exact amount, matching reference, and matching user metadata.
- Verification is idempotent, so refreshing the callback cannot credit the same payment twice.
- `fund-wallet.html` automatically verifies a returned Paystack reference.
- Request body limits were added and proxy trust is configured for hosted HTTPS environments.
- Accidental Markdown code fences were removed from the static HTML pages.

Data and airtime purchases call WiseSub and preserve pending status after
uncertain responses. Request IDs and matching-pending checks prevent repeat
debits for unresolved purchases. Admins can query provider status and manually
resolve pending transactions. Automatic refunds on WiseSub `failed` status stay
disabled until staging confirms the provider's terminal failure semantics.

## Python backend migration status (updated 2026-10-10)

`apps/api-python/` includes database-backed WiseSub plan sync, admin-managed
prices/categories/availability, categorized customer browsing, request
idempotency, and pending purchase reconciliation. It is not production-ready:
the suite passes 35 mocked SQLite tests plus a PostgreSQL-only race test that
was skipped; PostgreSQL schema and concurrency, Node tests, provider failure
semantics, and browser staging remain unverified.
See [the Python API guide](apps/api-python/README.md) and
[compatibility report](apps/api-python/COMPATIBILITY-REPORT.md). Keep Node live
until staging gates pass. No deploy, push, commit, production schema change, or
environment change was made.
