# MELODEXS CONNECT Handover

## 1. Project overview

MELODEXS CONNECT is a Node.js monorepo for a data and airtime reselling platform.
Users register, log in, manage purchase PINs, fund a wallet, and purchase mobile
data or airtime. Administrators can access usage summaries, user records, and
transaction data. The backend is built with Express and SQLite; the frontend is a
static HTML/CSS interface served by the API.

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
- `apps/api/src/config.js`: environment validation and shared config values such
  as `DB_PATH`, `WEB_PUBLIC_DIR`, and `PORT`.
- `apps/api/src/db.js`: SQLite database instance, schema creation, and migration
  helpers.
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
- database: SQLite lifecycle and schema migrations
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
- `DB_PATH`
- `WISESUB_BASE_URL`
- `WISESUB_API_KEY`
- `WISESUB_API_SECRET`
- `WISESUB_ENVIRONMENT`
- `CHEAPDATA_MARKUP_PERCENT`

Do not place real secret values in docs, scripts, or commits.

### Default database path

The default app database path is:

```text
./apps/api/data/cheapdata.db
```

This path is used by the SQLite setup and scripts unless `DB_PATH` is explicitly
set in `.env`.

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
session-based access control.

### Wallet and funding

- `POST /api/test-fund` — development-only funding route; disabled in production
- `POST /api/fund-wallet` — Paystack wallet funding initialization

Wallet funding uses Paystack and expects `PAYSTACK_SECRET_KEY` to be configured.
This is the live payment path and should only be tested with real credentials in a
proper environment.

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

The SQLite database is created in `apps/api/data/cheapdata.db` and uses SQLite
WAL and SHM sidecar files. These are ignored by Git.

The database setup includes:

- `users` table
- `transactions` table
- `data_plans` table with customer pricing plus WiseSub provider metadata
- schema migration checks for missing fields such as:
  - `purchase_pin`
  - `virtual_account_number`
  - `virtual_bank_name`
  - `kyc_status`
  - `is_admin`
  - `reset_token_hash`
  - `reset_token_expires_at`

The migration logic runs automatically when the app boots. This is important when
restoring or upgrading from an older database state.

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

These scripts depend on the WiseSub env variables and should only be run in the
intended environment.

## 9. Testing and linting

### Smoke test

The project includes a lightweight smoke test at:

- `apps/api/test/api-smoke.test.js`

This test runs with `NODE_ENV=test` and uses a temporary SQLite database created
and removed during the run. It verifies:

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
- Current automated coverage is smoke-level only. For production readiness, add
  route-level tests for authentication, purchase PIN flows, wallet funding,
  purchases, and admin authorization.

## 11. Verification status

This project has been validated with the following checks:

- JavaScript syntax checks on project files
- workspace install (`npm install`)
- SQLite database read/write validation
- API smoke test (`npm test`)
- ESLint validation (`npm run lint`)
- application boot through the dev command (`npm run dev`)

The app starts successfully and serves the frontend at `http://localhost:3000`
without module-resolution or database-path errors under the current setup.

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

Important: data and airtime purchase endpoints still record a successful debit locally; they do not yet call WiseSub to actually deliver the purchased service. The next major production step is to introduce a provider purchase layer with pending/success/failed states, provider references, and safe refund handling.
