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
