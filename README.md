# MELODEXS CONNECT

MELODEXS CONNECT is a data and airtime reselling platform. Customers create accounts,
fund a wallet through Paystack, and use their balance to purchase mobile data
and airtime. The Express API handles authentication, wallet operations,
purchases, transactions, and administration. The web workspace contains the
browser pages served by the API.

## Project structure

```text
.
├── apps/
│   ├── api/
│   │   ├── data/                 # Local SQLite database; ignored by Git
│   │   ├── scripts/              # Database, admin, and WiseSub utilities
│   │   ├── src/server.js         # Express API and static file server
│   │   └── package.json
│   └── web/
│       ├── *.html                # Customer and admin pages
│       ├── styles.css
│       └── package.json
├── .env.example                  # Configuration template
├── package.json                  # npm workspace root
├── package-lock.json
└── README.md
```

The root package owns only workspace-level commands. Backend dependencies and
development tools are declared in `apps/api/package.json`. The web workspace
currently uses plain HTML, CSS, and browser JavaScript and has no npm
dependencies.

## Requirements

- Node.js 18 or newer
- npm

## Install

Run this from the repository root:

```bash
npm install
```

Copy `.env.example` to `.env` and fill in the values required for the services
you use. Keep `.env` private and never commit real credentials.

## Run

Development mode, with automatic restart:

```bash
npm run dev
```

Production-style start:

```bash
npm start
```

The server listens on `PORT` and defaults to `3000`. Open
`http://localhost:3000` in a browser.

Run the isolated API smoke test with:

```bash
npm test
```

Tests run with `NODE_ENV=test` and use a temporary SQLite database at
`apps/api/data/cheapdata.test.db`. The test database is removed when the test
finishes, so development data is not modified.

Useful database commands:

```bash
npm run db:fix
npm run db:reset-fields
npm run db:purchase-pin
npm run make-admin
```

WiseSub utilities are available through the API workspace:

```bash
npm run wise:sync --workspace=@cheapdata/api
npm run wise:test --workspace=@cheapdata/api
npm run wise:test-mtn --workspace=@cheapdata/api
npm run wise:test-plans --workspace=@cheapdata/api
npm run wise:test-pricing --workspace=@cheapdata/api
```

## Environment variables

Use the existing `.env.example` as the source of truth. It defines:

- `PORT` and `NODE_ENV` for server operation
- `SESSION_SECRET` for signed session cookies
- `PAYSTACK_SECRET_KEY` for wallet funding
- `DB_PATH` for the SQLite database location
- `WISESUB_BASE_URL`, `WISESUB_API_KEY`, `WISESUB_API_SECRET`, and
	`WISESUB_ENVIRONMENT` for provider integration
- `CHEAPDATA_MARKUP_PERCENT` for customer pricing

The default database path is `./apps/api/data/cheapdata.db`. Database files and
SQLite journal files are ignored by Git.

## Security notes

Set a strong `SESSION_SECRET` in production. The API refuses to start in
production when it is missing. Do not expose Paystack or WiseSub credentials in
frontend code, documentation, logs, or commits.

### Wallet funding verification

Wallet funding uses a two-step flow. `/api/fund-wallet` initializes Paystack and records a pending transaction. After checkout, the frontend sends the returned reference to `/api/fund-wallet/verify`; the server verifies the payment with Paystack before crediting the wallet.

## Backend Architecture

MELODEXS CONNECT uses a modular Express/PostgreSQL backend.

The API is organized into:

```text
apps/api/src/
├── app.js
├── server.js
├── config/
├── routes/
├── controllers/
├── services/
├── middleware/
├── utils/
└── database/session modules
```

### Responsibilities

* `app.js` — Express application setup, global middleware, session configuration, webhook registration, route mounting, and centralized application setup.
* `routes/` — Defines API endpoints, HTTP methods, and middleware.
* `controllers/` — Handles HTTP requests/responses and coordinates application services.
* `services/` — Contains reusable business logic such as wallet operations, Paystack integration, and WiseSub integration.
* `middleware/` — Authentication, authorization, and other request middleware.
* `utils/` — Small reusable helpers such as reference generation, pricing, and validation.
* PostgreSQL/session modules — Database access and persistent session storage.

The backend is intentionally separated into modules so that payment, wallet, authentication, and telecom-service logic does not become concentrated in `app.js`.

## Payment Integrations

### Paystack

Paystack is used for wallet funding.

The production flow is:

```text
Customer
	↓
MELODEXS CONNECT wallet funding
	↓
Paystack checkout
	↓
Paystack callback
	↓
Server-side transaction verification
	↓
Paystack webhook
	↓
Wallet credited
```

Wallet crediting is performed only after server-side validation.

The Paystack webhook must remain registered before `express.json()` because the webhook signature is verified against the original raw request body.

The webhook validates the Paystack signature and checks the transaction reference, payment status, currency, amount, and user metadata before crediting a wallet.

Wallet funding is idempotent and uses PostgreSQL transaction/row-locking logic to prevent duplicate credits.

Never place a Paystack secret key in source code, frontend code, Git, or the README.

### WiseSub

WiseSub provides the telecom services used by MELODEXS CONNECT, including:

* Data purchases
* Airtime purchases

The environment is controlled through:

```text
WISESUB_ENVIRONMENT
```

Use `test` for sandbox testing and `live` for production.

WiseSub production requests use the configured partner API base URL and the appropriate production credentials stored in the deployment environment.

Never place WiseSub API keys or API secrets in source code, frontend code, Git, or the README.

## Environment Variables

The repository contains `.env.example` as a template.

Real secrets must never be committed to Git.

Typical variables include:

```text
NODE_ENV
PORT
DATABASE_URL
SESSION_SECRET
PAYSTACK_SECRET_KEY
CHEAPDATA_PUBLIC_URL
WISESUB_BASE_URL
WISESUB_API_KEY
WISESUB_API_SECRET
WISESUB_ENVIRONMENT
CHEAPDATA_MARKUP_PE
```

