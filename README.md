# MELODEXS CONNECT

MELODEXS CONNECT is a Nigerian digital services platform for wallet funding,
mobile data, airtime, and related digital services. Customers register, fund a
wallet, and use it to pay for services. The web app is a set of HTML, CSS, and
browser JavaScript pages served by the Express API.

## Features

- Account registration, login, password reset, and PostgreSQL-backed sessions
- Purchase PIN creation, change, and verification
- Wallet funding through Paystack checkout, server-side verification, and
  signed webhook processing
- WiseSub-powered mobile data and airtime purchases
- Transaction history and an admin panel
- WiseSub data plan pricing with a configurable markup
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

Requires Node.js 18 or newer and npm. From the repository root:

```bash
npm install
cp .env.example .env
npm run dev
```

The API defaults to port 3000. Open `http://localhost:3000` to use the web app.
For a production-style local start, run `npm run start` (or `npm start`).

## Testing and linting

```bash
npm test
npx eslint apps/api/src
```

The API smoke test connects to PostgreSQL, so it requires a dedicated test
PostgreSQL database configured in `DATABASE_URL`. Never point local tests at the
production database. The test checks API status and delivery of the home page;
it does not perform Paystack or WiseSub purchases.

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
