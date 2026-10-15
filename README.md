# MELODEXS CONNECT

MELODEXS CONNECT is a Nigerian digital services platform for wallet funding,
mobile data, airtime, and related digital services. Customers register, fund a
wallet, and use it to pay for services. The web app is a set of HTML, CSS, and
browser JavaScript pages currently served by the Express API.

## Features

- Account registration, login, password reset, and PostgreSQL-backed sessions
- Purchase PIN creation, change, and verification
- Wallet funding through Paystack checkout, server-side verification, and
  signed webhook processing
- WiseSub-powered mobile data and airtime purchases
- Transaction history and an admin panel
- WiseSub data plan pricing with a configurable markup
- Admin-triggered WiseSub catalog synchronization, admin-managed price
  overrides and categories, and customer network → category → plan browsing
- PostgreSQL persistence and deployment support for Render
- Installable progressive web app (PWA)

## MELODEXS CONNECT architecture

The project is a Node.js/Express API and a static browser app. The API is in
`apps/api/src`; `app.js` composes middleware and routers, and `server.js` starts
the HTTP listener. The API serves the web files in `apps/web`.

### Backend structure

- `routes/` maps HTTP methods and paths to authentication middleware and
  controllers. All API routers are mounted under `/api`.
- `controllers/` validates request input, coordinates application operations,
  and returns HTTP responses.
- `services/` owns provider communication and reusable wallet transactions.
- `utils/` contains shared pure helpers, currently Nigerian phone validation.
- `auth.js` provides authentication and admin authorization; `postgres.js`
  creates the PostgreSQL pool; `postgres-session-store.js` persists sessions.
- `scripts/` contains database maintenance and provider utility scripts.

### Routes

The route modules expose authentication and password reset, user status/profile,
transaction history, public and admin data plans, data and airtime purchases,
purchase PIN operations, admin reporting, and Paystack wallet funding. The
Paystack endpoints are `POST /api/fund-wallet`,
`POST /api/fund-wallet/verify`, and `POST /api/paystack/webhook`.

### Controllers

`auth.controller.js`, `user.controller.js`, `transaction.controller.js`,
`data-plan.controller.js`, `purchase.controller.js`,
`purchase-pin.controller.js`, `admin.controller.js`, and
`paystack.controller.js` handle their respective HTTP flows. Protected routes
retain authentication, admin checks, and user ownership checks.

### Services and utilities

- `paystack.service.js` performs Paystack requests and validates webhook
  signatures; `paystack.controller.js` handles funding records and wallet
  credits.
- `wisesub.service.js` sends WiseSub purchase requests.
- `wallet.service.js` reserves purchase funds and handles refunds and
  transaction finalization.
- `email.service.js` sends Brevo email for password reset.
- `utils/phone.js` centralizes the phone validation shared by registration and
  purchases.

The browser app is in `apps/web`; its pages use the shared API configuration in
`api.js`.

### PostgreSQL and database requirements

The running API and session store require PostgreSQL through `DATABASE_URL`.
There is no automatic SQLite fallback in the production API. `DB_PATH` is a
legacy SQLite setting for maintenance scripts only. Use a separate PostgreSQL
database for local testing; never use production data for tests.

## Paystack wallet funding

`POST /api/fund-wallet` validates the requested naira amount, records a pending
wallet transaction, and initializes Paystack using a generated reference. The
service converts naira to kobo once. Checkout returns to the configured public
URL at `/fund-wallet.html` (or the request host fallback).

After checkout, the client submits the reference to
`POST /api/fund-wallet/verify`. The server checks the payment with Paystack,
confirms the exact amount, NGN currency, reference, and user metadata, then
credits the wallet in a PostgreSQL transaction under `FOR UPDATE` row locking.

Paystack sends events to `POST /api/paystack/webhook`. This route is registered
before `express.json()` and uses the raw request body to validate the
`x-paystack-signature` HMAC-SHA512 signature. Only validated `charge.success`
events can credit a wallet. Transaction locking and status checks prevent
repeated credits.

## WiseSub

The API uses the WiseSub reseller API for mobile data and airtime. Set the
WiseSub base URL and credentials on the server. `WISESUB_ENVIRONMENT` selects
the configured `test` or `live` behavior; test mode uses a test recipient for
purchases. Live purchases must only be made with deliberate operator approval.

## Brevo email integration

Brevo HTTP communication is isolated in `email.service.js`. The auth controller
uses it to send password reset messages; registration does not send an email.
Configure the sender and API key on the server.

## PWA

The web app includes `manifest.webmanifest`, `pwa.js`, a service worker, and
192px, 512px, maskable, and Apple touch icons. The install prompt supports
browser installation and provides Add to Home Screen guidance on Apple mobile
devices. The service worker caches same-origin static assets only; it skips API
requests and non-GET requests, including payment and authentication operations.

## Environment variables

Copy `.env.example` to `.env` for local configuration. It lists variable names
and placeholders only. Keep real values private and configure production values
in the deployment environment.

- `NODE_ENV`, `PORT`: server mode and listening port.
- `DATABASE_URL`: PostgreSQL connection used by the API and automated smoke
  test. Use a dedicated test database for local tests, never the production
  database.
- `SESSION_SECRET`: signs protected session cookies.
- `PAYSTACK_SECRET_KEY`: server-side Paystack API and webhook key.
- `CHEAPDATA_PUBLIC_URL`: public frontend URL used for callbacks and password
  reset links. The existing name is retained for compatibility.
- `WISESUB_BASE_URL`, `WISESUB_API_KEY`, `WISESUB_API_SECRET`,
  `WISESUB_ENVIRONMENT`: WiseSub API configuration.
- `CHEAPDATA_MARKUP_PERCENT`: data plan price markup. The existing name is
  retained for compatibility.
- `BREVO_API_KEY`, `BREVO_FROM_EMAIL`, `BREVO_FROM_NAME`: password reset email
  delivery through Brevo.
- `DB_PATH`: legacy SQLite path used by some database maintenance scripts; the
  running API uses PostgreSQL through `DATABASE_URL`.

## Install and run

The Python API requires Python 3.11+ with the `apps/api-python/requirements.txt`
packages (`pip install -r apps/api-python/requirements.txt`). Node.js 18+ is
still used for the frontend tooling, the ESLint config, and the retained Node
rollback service. From the repository root:

```bash
npm install                      # frontend tooling
pip install -r apps/api-python/requirements.txt
cp apps/api-python/env.example .env   # then set NODE_ENV, SESSION_SECRET, ...
npm run dev                      # Python API on http://localhost:3000
```

`npm start` runs the Python API with production-style binding
(`0.0.0.0:${PORT:-3000}`); `npm run start:node` / `npm run dev:node` run the
retained Node backend instead. Environment variables are documented in
[apps/api-python/env.example](apps/api-python/env.example); startup fails
fast when required production configuration is missing or invalid.

### Database and admin utility scripts

These root `package.json` scripts exist for maintenance and are not part
of the normal install/run flow:

- `npm run db:fix` - repair/normalise database state after a failed purchase
- `npm run db:reset-fields` - reset wallet/transaction fields to a clean state
- `npm run db:purchase-pin` - manage purchase PIN records
- `npm run make-admin` - grant the admin role to a registered account

They talk to PostgreSQL through `DATABASE_URL`, so never point them at the
production database without a backup.

## Testing and linting

```bash
npm run test:api-python   # Python suite against a fresh external scratch SQLite database
npm test                   # Node smoke test (dedicated PostgreSQL test DB required)
npm run lint               # ESLint across the workspace
```

The Python suite creates its own throwaway SQLite database outside the
repository and never contacts PostgreSQL, providers, or production. The
PostgreSQL integration tests behind the opt-in gate are covered in
[apps/api-python/MIGRATION-STAGING.md](apps/api-python/MIGRATION-STAGING.md).
The Node smoke test connects to the configured `DATABASE_URL`, so it requires a
dedicated disposable test database. Never point any test at production. The
smoke test checks API status and delivery of the home page; it does not perform
Paystack or WiseSub purchases.

## Security

- Keep API keys, API secrets, database credentials, and session secrets on the
  server. Do not put them in frontend files or commit them.
- Paystack payments are verified server-side. Webhook signatures are checked
  against the original raw request body.
- Wallet credits are protected with PostgreSQL transactions, row locks, and
  idempotent transaction status checks.
- Production sessions use secure, HTTP-only cookies and HTTPS.
- The service worker caches only same-origin static assets. It does not cache
  API requests, account pages, wallet data, transactions, or admin responses.

Historical backup archives may contain legacy project material. They are not
active application source and must not be used as production configuration or
source.

## Deployment

The project is configured for the frontend and API to run as Render services.
Set production environment variables in the service configuration, use HTTPS,
and configure Paystack's webhook URL as
`https://melodexs-connect-api.onrender.com/api/paystack/webhook`.

## Python backend migration status

The Python backend (`apps/api-python/`, FastAPI) is the intended production
API after staging verification and release approval. It covers every route
the frontend calls (30 routes: the Node contract plus the category,
synchronization, pending-purchase, and reconciliation endpoints), and an
automated frontend-contract test fails the suite if the frontend and the
Python routes ever drift apart. The full audit, route-by-route matrix, and
evidence categories are in
[apps/api-python/COMPATIBILITY-REPORT.md](apps/api-python/COMPATIBILITY-REPORT.md);
verified test evidence is in
[apps/api-python/STAGING-TEST-EVIDENCE.md](apps/api-python/STAGING-TEST-EVIDENCE.md);
the step-by-step cutover and rollback plan is in
[apps/api-python/CUTOVER-CHECKLIST.md](apps/api-python/CUTOVER-CHECKLIST.md).

Current verified state (2026-10-15): Python suite 112 passed / 7
PostgreSQL-gated skips on external scratch SQLite; 7/7 PostgreSQL integration
tests on the disposable sandbox PostgreSQL 15.19; Node smoke test passed
against the same disposable database; all migrations verified idempotent with
migration 003 proven to fail safely on duplicates. Sessions do not transfer:
every user re-logs in once at cutover.

### Node dependency classification (Phase 7 audit)

| Reference | Class | Disposition |
|---|---|---|
| `apps/api/` Express service | A — production backend | Migrated to Python; **retained as a rollback artifact** until the Python deployment passes its observation period. Do not serve production traffic with it after cutover. |
| Root `npm start` / `npm run dev` | A — backend entry points | Now start the Python API. Node variants kept as `start:node` / `dev:node` / `api:node`. |
| `apps/web/` static frontend, Capacitor/Android, PWA | B — frontend/build | Unchanged; served by the API as static files and by the hosting provider. |
| ESLint config, Node tooling | B — build tooling | Retained. |
| `npm test` Node smoke test | C — regression testing | Retained; run only against a dedicated disposable test database. |
| `db:fix`, `db:reset-fields`, `db:purchase-pin`, `make-admin` scripts | C — maintenance | Retained as Node utilities; superseded for the Python path by the reviewed migrations, the schema checker, and admin flags. Ad-hoc DDL — never run against production without a backup. |
| `apps/api/scripts/wise:*` provider scripts | C — manual testing | Retained untouched; require live credentials and are not part of CI. |
| `HANDOVER.md`, `UPGRADE-NOTES.md`, `REBRAND-CHANGES.md` | D — historical documentation | Retained as history. |
| Nothing identified | E — unused | No removals were made; rollback capability is preserved. |

### Frontend API configuration

`apps/web/api.js` resolves the API origin in one place: the per-page
`api-base-url` meta tag (staging/preview), then the production API URL
constant, then the page origin for local development (a hosted page can never
resolve to localhost). The single cutover switch
`API_TARGET_IS_PYTHON` enables the category and reconciliation UI that only
the Python API provides; it stays `false` (Node behavior) until staging
verification and release approval. Flip it together with the production API
switch per the cutover checklist.

No production traffic, environment variables, database, or provider settings
were changed. Production still runs the Node backend until the cutover
checklist is fully PASS and a cutover is explicitly authorized.
