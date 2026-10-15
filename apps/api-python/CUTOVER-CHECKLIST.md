# Staging cutover and rollback checklist

Step-by-step plan for moving MELODEXS CONNECT from the Node backend
(`apps/api/`) to the Python backend (`apps/api-python/`), with acceptance
status for each criterion. Statuses reflect verified evidence from
2026-10-15 recorded in [STAGING-TEST-EVIDENCE.md](STAGING-TEST-EVIDENCE.md)
and [COMPATIBILITY-REPORT.md](COMPATIBILITY-REPORT.md).

Statuses: **PASS** (verified evidence), **PARTIALLY PASS** (verified in
part; the remainder is listed), **BLOCKED** (requires a resource that does
not exist yet — provider sandbox credentials, an approved staging copy of
data, or a hosting-dashboard action), **NOT TESTED** (not yet executed).
Nothing is FAIL. A real Render staging environment has existed since
2026-10-15 (see STAGING-TEST-EVIDENCE.md and
STAGING-DEPLOYMENT-RENDER.md), so the former "no staging" blockers are
resolved or narrowed below. **No step in this checklist touches production;
production deployment is a separate, explicitly authorized action after
this checklist is fully PASS.**

## Pre-cutover steps

### 1. Pre-cutover backup and recovery verification — BLOCKED (hosting access)

- Take a full logical backup of the production database and store it
  encrypted, outside the hosting account.
- Restore the backup into an isolated staging database and confirm the restore
  is complete and queryable.
- Required action: owner, in the hosting dashboard. Nothing can be verified
  until a staging environment exists.

### 2. Approved staging database identity checks — PASS (disposable + Render staging)

On the sandbox disposable PostgreSQL: host, database name, username, and TLS
`sslmode=verify-full` were verified, with a dedicated role and an empty
database. A hosting-provider staging database now exists (Render, `melodexs-connect-staging-db`,
free tier, expires 2026-11-14) and is reached over Render's internal network with a
dedicated generated role and database. It is a fresh empty database, not a copy of
production data; the identity checks passed at its creation and every boot connects
as that dedicated role.

### 3. Schema and migration verification — PASS (disposable + fresh staging) / BLOCKED (staging copy of real data)

- Migrations 001/002/003 verified on the disposable database: idempotent
  re-runs, preflight 0 duplicate groups / 0 rows, migration 003 proven to
  fail safely on duplicates, schema checker exit 0 after migration.
- The checker exits nonzero on incompatible schemas (new regression tests).
- **Remaining:** run the same preflights and migrations against an approved
  staging copy of real data. The preflight may return duplicates there; if
  so, stop and resolve deliberately — never delete rows automatically.
- **Staging evidence (2026-10-15):** the base schema plus migrations
  001/002/003 were applied to the fresh Render staging database before first
  boot; the startup schema check passes on every boot (it hard-fails if any
  migration object is missing), and a registration on staging received a
  database-generated user id — identity-backed primary keys confirmed on the
  staging database.
- **Critical unknown:** whether the *production* schema's primary keys
  generate IDs on insert (the staging database was provisioned with the new
  base schema, so it does not answer this). The Python API omits IDs on insert and requires
  identity/sequence-backed primary keys; the old Node DDL may declare bare
  `INTEGER PRIMARY KEY`. The schema checker detects this
  (`missing_generated_id_defaults`) and must be run against the staging copy
  before any cutover traffic.

### 4. Environment variables and secret configuration — PASS (staging core) / NOT TESTED (provider credentials)

**Staging (PASS, 2026-10-15):** `NODE_ENV`, `DATABASE_URL` (internal
Render connection string), `SESSION_SECRET`, `WISESUB_ENVIRONMENT`,
`CHEAPDATA_PUBLIC_URL`, and `FORWARDED_ALLOW_IPS` are set on the staging
service; startup validation passes (misconfigurations were observed to
refuse boot during deploy attempts, which is the validation working).
**NOT TESTED:** provider credentials (WiseSub key/secret, Paystack test
keys, Brevo test key) are not configured on staging — owner action. No
value is or ever was committed; the staging secret was rotated on
2026-10-15 during an env-var restore, invalidating prior staging sessions.

### 5. Python API deployment to staging only — PASS (Render staging, live)

Deploy `apps/api-python/` to a staging service (e.g. a Render staging web
service) with the ASGI start command from `apps/api-python/README.md`. Do not
change the production frontend's API target and do not deploy to the
production service.

### 6. Health and readiness verification — PASS (staging)

**Staging (PASS, 2026-10-15):** the staging API is live;
`GET /api/status` returns 200 success; the Render health check is green;
migrations never run at boot (the one-shot provisioning used a temporary
start command, since restored; the leftover pre-deploy hook must be removed
in the dashboard — see STAGING-DEPLOYMENT-RENDER.md).

### 7. Frontend-to-API compatibility checks — PARTIALLY PASS (staging browser walkthrough done; category-5 side-by-side matrix NOT TESTED)

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

### 8. Login/session behavior and user re-login — PARTIALLY PASS (automated + staging browser/API checks; wide-device browser matrix NOT TESTED)

Automated regression tests prove: a request with only a legacy `connect.sid`
cookie is anonymous; logout clears both cookie names; sessions are stored
server-side and expire. **Staging (2026-10-15):** the browser walkthrough on the staging
frontend (register, purchase-PIN creation, logout, login, dashboard
loading) passed, and API-level checks confirmed `melodexs_session` is set,
accepted, and authenticates requests over HTTPS. Session-cookie flags were
verified by the local Render-style simulation (Secure; HttpOnly;
SameSite=none) — a full cross-browser matrix on staging is still open.

### 9. Payment/provider sandbox verification — BLOCKED (provider sandbox)

- Paystack test keys, a sandbox funding flow, and webhook signature checks.
- WiseSub test credentials: sync, package removal, timeout/status reference,
  terminal-failure semantics (decides `WISESUB_FAILURE_STATUS_CONFIRMED`).
- Brevo test-mode email for password reset.
- No live purchase or real customer email at any point in staging.

### 10. Purchase and transaction consistency checks — NOT TESTED (blocked on provider sandbox, step 9)

Pending/success/failure/refund transitions, wallet balance integrity,
reconciliation of pending purchases, and duplicate-request idempotency against
the staging copy. The equivalent concurrent behaviors passed on the
disposable PostgreSQL (7/7 integration tests); staging re-verifies them with
real-shaped data.

### 11. Monitoring and alerting — PARTIALLY PASS (Render logs verified secret-free; free-tier retention is minutes; alerting NOT TESTED)

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

### 14. Rollback safety verification (Node can read Python-era data) — PARTIALLY PASS (disposable cross-read proven) / NOT TESTED (Node smoke against staging DB)

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

| # | Blocker | Status 2026-10-15 | Required action | Responsible |
|---|---|---|---|---|
| 1 | No staging environment | **RESOLVED** — Render staging (API, frontend, PostgreSQL) live since 2026-10-15 | Re-provision before the free-tier database expires 2026-11-14 if staging must persist | Owner |
| 2 | Schema ID defaults | **PASS on staging** (registration received a database-generated id). The **production** schema remains the unknown | Run the schema checker against an approved production data copy before cutover; resolve `missing_generated_id_defaults` | Owner + operator |
| 3 | No side-by-side runtime comparison | **NOT TESTED** | Run the route matrix against both backends (step 7, category 5) | Operator |
| 4 | Provider sandbox unverified | **BLOCKED** — no WiseSub/Paystack/Brevo test credentials on staging; the plan catalog is empty until a WiseSub sync runs | Configure provider test credentials on staging (step 9) | Owner |
| 5 | Browser walkthrough | **DONE (staging)** — register/PIN/login/logout/dashboard verified on 2026-10-15 | Extend to purchase, admin, and reconciliation journeys after step 9 | Operator |
| 6 | Staging uses a fresh empty database, not a copy of real data | **BLOCKED (data copy)** | Restore an approved production backup into staging and re-run preflights (step 1) | Owner |
| 7 | Node smoke test against the staging database | **NOT TESTED** | Run the Node API briefly against the migrated staging database to confirm rollback cross-read (step 14) | Operator |
| 8 | Leftover pre-deploy migration hook on staging | **BLOCKED (dashboard-only)** | Remove the Pre-Deploy Command in the staging service dashboard | Owner |

## Verdict

**STAGING DEPLOYED AND PARTIALLY VERIFIED — NOT READY FOR CUTOVER.**
The Python backend is live on Render staging with the frontend walkthrough,
session, CORS, admin-gate, and health checks passing (2026-10-15). The
remaining blockers are provider sandbox credentials, an approved staging
copy of real data (with the production-schema ID-default check that only a
real copy can answer), the side-by-side route matrix, the Node smoke test
against the staging database, and the removal of the staging pre-deploy
hook. Production traffic remains on Node; the merged `master` is deployed
only to staging; a production cutover requires this checklist fully PASS
plus separate explicit authorization. Nothing here constitutes cutover
approval.
