# Staging cutover and rollback checklist

Step-by-step plan for moving MELODEXS CONNECT from the Node backend
(`apps/api/`) to the Python backend (`apps/api-python/`), with acceptance
status for each criterion. Statuses reflect verified evidence from
2026-10-15 recorded in [STAGING-TEST-EVIDENCE.md](STAGING-TEST-EVIDENCE.md)
and [COMPATIBILITY-REPORT.md](COMPATIBILITY-REPORT.md).

Statuses: **PASS** (verified evidence), **BLOCKED** (requires a resource that
does not exist yet — staging environment, hosting credentials, provider
sandbox, or an approved staging copy of data). Nothing is FAIL. **No step in
this checklist touches production; production deployment is a separate,
explicitly authorized action after this checklist is fully PASS.**

## Pre-cutover steps

### 1. Pre-cutover backup and recovery verification — BLOCKED (hosting access)

- Take a full logical backup of the production database and store it
  encrypted, outside the hosting account.
- Restore the backup into an isolated staging database and confirm the restore
  is complete and queryable.
- Required action: owner, in the hosting dashboard. Nothing can be verified
  until a staging environment exists.

### 2. Approved staging database identity checks — PASS (disposable only) / BLOCKED (provider staging)

On the sandbox disposable PostgreSQL: host, database name, username, and TLS
`sslmode=verify-full` were verified, with a dedicated role and an empty
database. A hosting-provider staging database does not exist yet; the same
checks must be repeated there before use.

### 3. Schema and migration verification — PASS (disposable) / BLOCKED (staging copy)

- Migrations 001/002/003 verified on the disposable database: idempotent
  re-runs, preflight 0 duplicate groups / 0 rows, migration 003 proven to
  fail safely on duplicates, schema checker exit 0 after migration.
- The checker exits nonzero on incompatible schemas (new regression tests).
- **Remaining:** run the same preflights and migrations against an approved
  staging copy of real data. The preflight may return duplicates there; if
  so, stop and resolve deliberately — never delete rows automatically.
- **Critical unknown:** whether the deployed schema's primary keys
  generate IDs on insert. The Python API omits IDs on insert and requires
  identity/sequence-backed primary keys; the old Node DDL may declare bare
  `INTEGER PRIMARY KEY`. The schema checker detects this
  (`missing_generated_id_defaults`) and must be run against the staging copy
  before any cutover traffic.

### 4. Environment variables and secret configuration — BLOCKED (hosting access)

Required Python API configuration (values from a secret manager, never from
the repository): `NODE_ENV=production`, `DATABASE_URL` (PostgreSQL,
`sslmode=verify-full`), `SESSION_SECRET` (32+ chars), `WISESUB_*` provider
configuration, Paystack keys, Brevo key, CORS origin list. Startup validates
these and fails fast when missing or invalid. Verify each variable in the
staging service configuration before deployment.

### 5. Python API deployment to staging only — BLOCKED (hosting access)

Deploy `apps/api-python/` to a staging service (e.g. a Render staging web
service) with the ASGI start command from `apps/api-python/README.md`. Do not
change the production frontend's API target and do not deploy to the
production service.

### 6. Health and readiness verification — BLOCKED (staging)

After staging deployment: `GET /api/status` returns success; logs show the
read-only schema check passing; no startup DDL occurred.

### 7. Frontend-to-API compatibility checks — BLOCKED (staging)

Point a **separate staging copy** of the frontend at the staging Python API
via the `api-base-url` meta tag (this also enables the categorized catalog UI
on the staging copy). The production frontend stays on Node. Run the
route-by-route matrix in COMPATIBILITY-REPORT.md against both backends
(side-by-side runtime comparison, category 5).

**Production frontend API switch (release-approval step):** `apps/web/api.js`
holds exactly two cutover controls — the `PRODUCTION_API_URL` constant and
`API_TARGET_IS_PYTHON`. At the approved production cutover: keep
`PRODUCTION_API_URL` as the (now Python-serving) API origin and flip
`API_TARGET_IS_PYTHON` to `true` so the category and reconciliation UI goes
live. To roll back the frontend, flip it back to `false`; nothing else in the
frontend encodes an API target. An automated frontend-contract test
(`tests/test_frontend_contract.py`) fails the Python suite if frontend calls
and Python routes ever drift apart.

### 8. Login/session behavior and user re-login — PARTIALLY PASS (automated) / BLOCKED (browser)

Automated regression tests prove: a request with only a legacy `connect.sid`
cookie is anonymous; logout clears both cookie names; sessions are stored
server-side and expire. The browser walkthrough (cookie flags, SameSite,
Secure, cross-origin behavior) requires staging.

### 9. Payment/provider sandbox verification — BLOCKED (provider sandbox)

- Paystack test keys, a sandbox funding flow, and webhook signature checks.
- WiseSub test credentials: sync, package removal, timeout/status reference,
  terminal-failure semantics (decides `WISESUB_FAILURE_STATUS_CONFIRMED`).
- Brevo test-mode email for password reset.
- No live purchase or real customer email at any point in staging.

### 10. Purchase and transaction consistency checks — BLOCKED (staging)

Pending/success/failure/refund transitions, wallet balance integrity,
reconciliation of pending purchases, and duplicate-request idempotency against
the staging copy. The equivalent concurrent behaviors passed on the
disposable PostgreSQL (7/7 integration tests); staging re-verifies them with
real-shaped data.

### 11. Monitoring and alerting — BLOCKED (hosting access)

Confirm staging logs are captured, error rates and health checks are
monitored, and alerts reach the owner. Safe logging is already implemented
(no credentials, tokens, or hash values in logs).

### 12. Rollback triggers — DEFINED

Abort or roll back the cutover if any of the following occurs:

- `/api/status` unhealthy or schema check fails after deployment.
- Login, registration, password reset, purchase, or wallet flows fail in
  walkthrough.
- Payment/provider flows are wrong or inconsistent.
- Data integrity anomalies (balances, transactions, plan catalog).
- Error-rate or latency alerts breach the agreed thresholds.

### 13. Exact rollback steps (application traffic) — DEFINED, untested in staging

Rolling back **application traffic** and rolling back **database schema** are
different operations; both differ from **data recovery**:

- **Roll back application traffic (primary path):** repoint the staging
  frontend back to the Node API (clear the `api-base-url` meta value), keep
  the Node service running, and stop the Python service. No data change is
  needed for this step **only if** step 14 has been confirmed.
- **Roll back database schema:** the migrations are additive (new tables,
  columns, indexes). Node ignores the added columns and tables, so schema
  rollback is normally **unnecessary** — leaving the additive schema in place
  is the recommended path. Destructive schema changes (dropping migration
  002 columns) would risk data loss and require an independently reviewed,
  separately authorized migration. Never improvise schema rollback during an
  incident.
- **Recover data:** restore from the pre-cutover backup (step 1) into a fresh
  database only after a documented data-loss incident, then repoint traffic.
  This is the last resort; it loses all post-backup writes.

### 14. Rollback safety verification (Node can read Python-era data) — BLOCKED (staging)

- **Python inserts omit IDs and require generated primary keys**; Node's DDL
  may not have them. If Python was allowed to write to a database whose
  primary keys are not generated, the failure occurs at insert time (Python
  refuses to write bare-integer-PK rows), so silent divergence is unlikely —
  but confirm the staging copy's ID defaults (step 3) before cutover.
- Node reads and writes only the original columns; migration 002's added
  columns and tables are invisible to it. Confirm on the staging copy that
  Node runs correctly against a migrated schema (run the Node smoke test
  against staging before declaring rollback safe).
- Sessions: after rollback, users created on Python (session store rows)
  must re-login on Node; `connect.sid` is reissued. Wallet and transaction
  rows written by Python use the same column contracts and are readable by
  Node.
- **Do not declare rollback safe until steps 1–3 pass against the staging
  copy and the Node smoke test has been run against the migrated staging
  database.**

### 15. Post-cutover checks (after a future, separately authorized production cutover) — DEFINED

- Monitor `/api/status`, error rates, purchase success rates, and wallet
  consistency for the first 48 hours.
- Announce the expected one-time re-login to users.
- Keep the Node service deployable and the pre-cutover backup for the agreed
  rollback window.
- Review admin sync/reconciliation outputs on the first business day.

## Outstanding blockers (owner actions required)

| # | Blocker | Required action | Responsible |
|---|---|---|---|
| 1 | No staging environment | Provision hosting staging (service + PostgreSQL) and restore an approved data copy | Owner |
| 2 | Production/staging schema ID defaults unknown | Run the schema checker against the staging copy; resolve any `missing_generated_id_defaults` | Owner + operator |
| 3 | No side-by-side runtime comparison | Run matrix against both backends on staging (step 7) | Operator |
| 4 | Provider sandbox unverified | Configure Paystack/WiseSub/Brevo test credentials on staging (step 9) | Owner |
| 5 | Browser walkthrough not executed | Execute steps 6–10 on staging | Operator |

## Verdict

**READY FOR STAGING DEPLOYMENT.** All locally verifiable criteria pass with
recorded evidence; the remaining criteria are blocked on staging access, not
on code. Do not treat the merged `master` as deployed or production-ready;
production traffic remains on Node until this checklist is fully PASS and a
separate cutover is explicitly authorized.
