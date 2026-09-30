# MELODEXS CONNECT FastAPI compatibility audit

Audit date: 2026-09-30. Reference implementation: `apps/api/`. Audited
implementation: `apps/api-python/`. No deployment, production database write,
real payment, real WiseSub purchase, or real email was performed.

## A. Routes

| Node route | Python route | Result | Important difference |
|---|---|---|---|
| `GET /api/status` | same | Compatible | Node includes a different status message string. |
| `GET /api/session` | same | Partial | Python uses a different cookie and session payload format. |
| `POST /api/register` | same | Partial | Main success shape is similar; FastAPI validation errors use `detail` rather than Node `message`. |
| `POST /api/login` | same | Partial | Same issue for framework-generated errors. |
| `POST /api/logout` | same | Partial | Python deletes its own cookie and attempts to delete `connect.sid`; it cannot invalidate an Express cookie it cannot decode. |
| `POST /api/forgot-password` | same | Partial | Provider errors are not normalized to Node’s exact response. |
| `POST /api/reset-password` | same | Partial | Same business fields, but framework error formatting differs. |
| `GET /api/user/:id` | `GET /api/user/{user_id}` | Partial | Python returns a profile without Node’s separate `has_purchase_pin` top-level field and uses a different authorization message. |
| `GET /api/transactions/:userId` | `GET /api/transactions/{user_id}` | Partial | Node permits an authenticated admin to view another user; Python currently rejects any user ID other than the session user. |
| `GET /api/data-plans` | same | Compatible | Same public plan fields and WiseSub-source filtering. |
| `GET/POST/PATCH /api/admin/data-plans[/:id]` | same | Partial | Routes exist; exact validation/messages and response fields need staging comparison. |
| `POST /api/purchase-data` | same | Partial | Python does not use PostgreSQL row locks and has different provider-error handling. |
| `POST /api/purchase-airtime` | same | Partial | Python does not map network names to Node’s WiseSub provider codes and omits Node’s ₦50–₦50,000 integer validation. |
| `POST /api/fund-wallet` | same | Partial | Paystack payload is similar; transaction rollback/initialization error normalization differs. |
| `POST /api/fund-wallet/verify` | same | Partial | Python lacks the Node row-locking/idempotency transaction boundary. |
| `POST /api/paystack/webhook` | same | Partial | Signature and validation exist, but Python lacks the Node `FOR UPDATE` lock. |
| `POST /api/purchase-pin/set/change/verify` | same | Partial | Core bcrypt behavior exists; exact error response formatting differs. |
| `GET /api/admin/stats/users/transactions` | same | Partial | Core queries exist; exact PostgreSQL behavior and response types need staging verification. |

No Node API route is intentionally omitted from the Python route set. The
WiseSub service helper routes (`/services`, `/packages`) are provider helper
calls in Node scripts, not public Express API routes; Python currently exposes
purchase calls only and has no equivalent plan-sync helper module.

## B. Database

The active Node runtime uses PostgreSQL tables `users`, `data_plans`,
`transactions`, and `sessions`; balances are stored on `users`. Python creates
the same four table names additively for an empty SQLite/PostgreSQL database.

Risks and differences:

- Python’s `CREATE TABLE IF NOT EXISTS` does not migrate missing columns on an
  already-existing PostgreSQL table.
- Python’s schema does not reproduce all indexes, foreign keys, and production
  column types/constraints from the Node migration script.
- Python purchase and wallet operations do not use PostgreSQL `FOR UPDATE`.
- Python’s SQLite compatibility is test-oriented; PostgreSQL production
  compatibility is **NOT VERIFIED**.
- No destructive migration was run.

## C. Authentication

Password hashing uses bcrypt and is compatible with the Node bcrypt hashes.
Registration auto-login, login, logout, reset token hashing, 15-minute reset
expiry, and purchase PIN hashing are implemented.

Session migration is not transparent. Node uses the signed `connect.sid` cookie
and stores JSON such as `{"cookie":...,"userId":...}`. Python uses a signed
`melodexs_session` cookie and stores `{"userId":...}`. Python can read the
`userId` member of an existing session row only after receiving its own cookie;
it cannot decode or adopt the Express cookie. Users must log in again after a
cutover unless a deliberate cookie/session migration is implemented.

## D. Wallet and transactions

The basic reserve, debit, refund, success, insufficient-balance, and Paystack
credit flows exist. They are not behaviorally equivalent under concurrency:
Node uses PostgreSQL transactions and row locks; Python currently performs
separate updates. This is a production blocker for financial operations.

Python also treats a number of WiseSub failures as an immediate refund where
Node returns HTTP 202 pending for provider/network uncertainty. Airtime network
provider-code mapping and amount bounds differ from Node.

## E. Paystack

Implemented and locally mocked: initialization payload, verification lookup,
raw-body HMAC-SHA512 signature validation, amount/currency/reference/metadata
checks, unsigned webhook rejection, and duplicate-success checks.

Not verified: real Paystack HTTP behavior, PostgreSQL locking/idempotency under
concurrent webhook delivery, and production credentials. Production Paystack
compatibility: **NOT VERIFIED**.

## F. WiseSub

The Python adapter preserves the base URL, bearer key, API secret,
environment header, JSON purchase payloads, and 30-second timeout. External
requests were not made. Provider plan retrieval (`GET /services` and
`GET /packages`) and Node’s helper behavior are not yet ported to Python.

WiseSub compatibility: **MOCKED/PARTIAL**, not production verified.

## G. Brevo

The Python adapter uses `https://api.brevo.com/v3/smtp/email`, the `api-key`
header, sender name/email, recipient list, subject, and HTML content. It was
not called with credentials. Error and password-reset delivery behavior remain
mock/staging items.

## H. Admin

Admin authorization is present for statistics, users, transactions, and data
plans. Admin behavior is not production verified. The transaction endpoint’s
admin cross-user access difference is listed above. Exact plan validation,
inactive-plan behavior, and PostgreSQL response types require staging tests.

## I. Security

Python has secure production-cookie settings, origin checks, security headers,
request rate limiting for auth routes, bcrypt, input checks, and webhook HMAC.

Differences/risks:

- FastAPI’s default exception responses expose `{"detail": ...}` instead of
  Node’s consistent `{"success": false, "message": ...}` contract.
- The in-memory rate limiter is process-local and not suitable for multiple
  Render instances.
- Python does not reproduce Helmet’s complete header behavior.
- The production database/session cookie migration has not been verified.
- Financial writes lack Node’s row locks.

## J. Frontend compatibility

All inspected frontend paths use the same `/api` paths and methods, and no
frontend files were changed. The frontend should reach the Python routes, but
exact runtime compatibility is partial because several response/error fields
and the session cookie differ.

## K. Production blockers

Before switching Render from Node to Python, resolve and verify:

1. Match Node’s error JSON and all exact success response fields/status codes.
2. Decide and test the Express-to-Python session-cookie migration strategy.
3. Add PostgreSQL migrations/introspection for existing columns and constraints.
4. Reimplement wallet and purchase transactions with PostgreSQL row locking and
   idempotent concurrent updates.
5. Match WiseSub airtime provider mapping, pending/refund semantics, and plan
   retrieval/sync helpers.
6. Add mocked and PostgreSQL integration coverage for all financial paths.
7. Verify Paystack, WiseSub, and Brevo against staging credentials without real
   financial transactions.
8. Replace the process-local limiter with a deployment-safe limiter.
9. Perform a full frontend staging walkthrough, including admin and reset flows.

## Follow-up remediation status
Verified in this branch:
- Node-shaped JSON error handlers now cover HTTP and validation errors.
- PostgreSQL purchase and Paystack credit paths include FOR UPDATE; SQLite tests use the same transaction code without PostgreSQL-only syntax.
- Airtime validation requires integer N50-N50000 amounts and maps MTN, Airtel, Glo, and 9mobile to Node WiseSub provider codes.
- WiseSub 5xx/network failures return pending HTTP 202; provider rejection and unsuccessful responses refund with HTTP 502.
- Auth and financial rate limits use the PostgreSQL-backed api_rate_limits table, with SQLite test fallback.
- app.schema_check provides a read-only schema comparison command.
Still not verified:
- PostgreSQL production compatibility and concurrent database behavior.
- Real Paystack, WiseSub, and Brevo staging calls.
- Full browser/frontend staging walkthrough.
- Express session-cookie migration; Python intentionally retains melodexs_session.
