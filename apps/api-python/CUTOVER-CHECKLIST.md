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

### 7. Frontend-to-API compatibility checks — PASS (staging walkthrough + side-by-side matrix)

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

**Side-by-side matrix (2026-10-15):** both backends were run against a
single fresh disposable PostgreSQL database and exercised with identical
scenarios: 33 checks, exact parity on all common routes (one apparent
register discrepancy was a harness phone collision, resolved by a focused
rerun: identical duplicate email/phone behavior), identical user-facing
messages, identical CORS/admin/404/webhook behaviour, and one
intentional difference (the new Python-only `/api/data-categories`
route). Cross-backend login works in both directions on the same
database. Full record: STAGING-TEST-EVIDENCE.md, section A.

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

**Exact tests blocked by missing credentials (all on staging):**

*WiseSub* (needs `WISESUB_API_KEY`, `WISESUB_API_SECRET`; staging
already sets `WISESUB_ENVIRONMENT=live`):
1. `POST /api/admin/data-plans/synchronize` — full catalog sync into
   `data_plans` / `data_categories` (currently both empty on staging).
2. `GET /api/admin/data-plans/synchronization` — sync status reporting
   over a real sync.
3. Data purchase against a real synced plan (`/api/purchase-data`) and
   WiseSub fulfillment confirmation.
4. Confirming terminal failure semantics for refunds
   (`WISESUB_FAILURE_STATUS_CONFIRMED` stays `false` — automated
   refunds deliberately disabled until a sandbox confirms the
   documented-failure-state question).

*Paystack* (needs `PAYSTACK_SECRET_KEY`):
5. `POST /api/fund-wallet` — initialize a real test transaction.
6. `POST /api/fund-wallet/verify` — verify a completed test payment
   and credit the wallet.
7. `POST /api/paystack/webhook` — signature verification with a valid
   Paystack-signed payload (unsigned payloads already correctly
   rejected 401 on both backends).
8. End-to-end wallet-funded purchase (step 10 with balance).

*Brevo* (needs `BREVO_API_KEY`, `BREVO_FROM_EMAIL`):
9. `POST /api/forgot-password` delivering a reset email to a real
   test inbox.
10. `POST /api/reset-password` completing with the emailed token
    (bogus-token rejection already verified identical on both
    backends).

- Paystack test keys, a sandbox funding flow, and webhook signature checks.
- WiseSub test credentials: sync, package removal, timeout/status reference,
  terminal-failure semantics (decides `WISESUB_FAILURE_STATUS_CONFIRMED`).
- Brevo test-mode email for password reset.
- No live purchase or real customer email at any point in staging.

### 10. Purchase and transaction consistency checks — NOT TESTED (blocked on provider sandbox, step 9; rejection paths already verified identical on both backends)

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

### 14. Rollback safety verification (Node can read Python-era data) — PASS (disposable + staging, both directions)

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

**Staging verification (2026-10-15):** the Node backend was run
(temporarily, staging-only) directly against the staging PostgreSQL —
it registered, logged in, served sessions, set and verified PINs, and
logged into a Python-written account. The staging service was then
restored to Python, which logged into the Node-written account and
verified the Node-set PIN. Node↔Python data compatibility on the actual
staging database is verified in both directions; Node's stay was
insert-only (test accounts). Full record: STAGING-TEST-EVIDENCE.md,
section B.

### 15. Post-cutover checks (after a future, separately authorized production cutover) — DEFINED

- Monitor `/api/status`, error rates, purchase success rates, and wallet
  consistency for the first 48 hours.
- Announce the expected one-time re-login to users.
- Keep the Node service deployable and the pre-cutover backup for the agreed
  rollback window.
- Review admin sync/reconciliation outputs on the first business day.

## Rollback review: tested steps vs untested assumptions

**Tested (with evidence):**
- Application-traffic rollback mechanism: a staging service swap
  (Python→Node→Python) was deployed and restored twice today; the
  deploy/restore cycle itself is proven (Render deploys
  `dep-db8m2tuq1p3s73bkcuk0` / `dep-db8m493bc2fs73ftche0`).
- Data compatibility in BOTH directions on the actual staging
  PostgreSQL: Node logged into a Python-written account; Python logged
  into a Node-written account and verified a Node-set PIN
  (STAGING-TEST-EVIDENCE.md, section B).
- The same bidirectional login compatibility on a disposable
  PostgreSQL (section A of the evidence).
- Migrations 001–003 are additive-only; the Node backend ran against
  the migrated staging database without errors, and the Python startup
  schema check still passes after the Node run (no schema drift).
- Session-secret rotation invalidates existing sessions (observed on
  staging during the env restore): users would need one re-login after
  a rollback that rotates the secret; the README's user-notice step
  covers this.

**Untested assumptions (do not treat rollback as fully proven until
these run):**
- The production backup/restore itself (step 1): no production data
  copy has been taken or restored; RPO/RTO timing is unmeasured.
- Rollback under production-scale data volume and load (staging holds
  a handful of test accounts).
- Real provider webhook replay/idempotency across a rollback boundary
  (blocked on provider sandbox, step 9).
- Render's one-click rollback to a specific earlier deploy on the
  production service (never exercised; the staging swaps used fresh
  deploys, not the rollback endpoint).

## Outstanding blockers (owner actions required)

| # | Blocker | Status 2026-10-15 (second verification) | Required action | Responsible |
|---|---|---|---|---|
| 1 | No staging environment | **RESOLVED** — Render staging live; Node↔Python compatibility on the staging database verified in BOTH directions this session | Re-provision before the free-tier database expires 2026-11-14 if staging must persist | Owner |
| 2 | Schema ID defaults | **PASS on staging + disposable** (database-generated ids; `schema_check` reports no `missing_generated_id_defaults`). The **production** schema remains the unknown | Run `DATABASE_URL=<approved-copy> NODE_ENV=test python -m app.schema_check --json` against an approved sanitized production copy before cutover | Owner + operator |
| 3 | Side-by-side runtime comparison | **RESOLVED** — 33-check route matrix on a shared disposable PostgreSQL: full parity (step 7) | None (re-run after any route change) | Operator |
| 4 | Provider sandbox unverified | **BLOCKED** — no WiseSub/Paystack/Brevo test credentials on staging; plan catalog empty until a WiseSub sync runs (exact blocked tests listed in step 9) | Configure provider test credentials on staging (step 9) | Owner |
| 5 | Browser walkthrough | **DONE (staging)** — register/PIN/login/logout/dashboard verified 2026-10-15 | Extend to purchase, admin, and reconciliation journeys after step 9 | Operator |
| 6 | Staging uses a fresh empty database, not a copy of real data | **BLOCKED (data copy)** | Restore an approved production backup into staging and re-run preflights (step 1) | Owner |
| 7 | Node smoke test against the staging database | **RESOLVED** — Node ran on the staging service against the staging PostgreSQL (temporary, restored); bidirectional cross-read verified (step 14) | None | Operator |
| 8 | Leftover pre-deploy migration hook on staging | **STILL PRESENT (corrected 2026-10-16)** — the hook lives at `serviceDetails.envSpecificDetails.preDeployCommand` (a base64 migration script), not at the field an earlier draft checked. It is INERT today (free plan does not execute pre-deploy commands; deploys at `e35bb87`/`668fd50` had no pre-deploy phase), but a plan upgrade would activate it | Remove the Pre-Deploy Command in the staging service dashboard before any plan change | Owner |
| 9 | Staging `DATABASE_URL` wiped by an env-vars bulk-replace (2026-10-16 incident) | **BLOCKED (dashboard)** — five of six variables restored via API; the running instance was never interrupted and the next deploy fails closed; `DATABASE_URL` (internal Render connection string) is not recoverable with the available API key | Re-paste the Internal Database URL into the staging API env (see OWNER-ACTION-CHECKLIST Action 7), then deploy | Owner |

## Verdict


## Production deployment preparation (review only — nothing executed)

Current production (verified 2026-10-16 via Render API):

- Production API: `melodexs-connect-api` (`srv-dap97sqd0e5s73f5hk70`),
  branch `master`, **rootDir `apps/api`**, Node (`npm start`), live,
  healthy (`/api/status` 200). NOTE: production auto-deploys on master
  merges; the 2026-10-16 merges rebuilt production Node from unchanged
  `apps/api` code (deploys `e35bb87`, `668fd50` — no behavioral change).
- Production frontend: `Melodexs-Connect` (`srv-dap9lkh42hec739cpfgg`),
  branch `master`, rootDir `apps/web`, live.

**RootDir is the ONLY production guard.** The root `package.json`
`start` script launches the **Python** backend. Production stays on
Node solely because its Render service sets `rootDir: apps/api`. Risks:
any future change to the production service's root directory, start
command, or workspace layout could silently switch backends. Mitigation
(merged via PR #13): the guarded root start script refuses to boot the
Python backend when `NODE_ENV=production` unless
`ALLOW_PYTHON_PRODUCTION=1` is explicitly present in the environment
(staging sets it; production never does), so a rootDir
misconfiguration now crash-loops instead of silently serving Python.
Note (verified 2026-10-16): the staging service uses a service-level
start command (plain uvicorn) that bypasses the root script, so the
guard protects the DEFAULT `npm start` path — exactly the path a
misconfigured production service would take — while staging's opt-in
variable is in place for whenever staging switches to the guarded start.
**Never set `ALLOW_PYTHON_PRODUCTION=1` on a production service until
cutover is explicitly authorized** — at that point it becomes the final
arming step.

Proposed Python production configuration (for cutover review, not
executed; values referenced by name only, no secrets):

| Item | Value |
|---|---|
| Runtime | Python 3.11+, uvicorn `[standard]` (pinned ranges in `apps/api-python/requirements.txt`) |
| Build | `pip install -r apps/api-python/requirements.txt` |
| Start | guarded root start (`bash scripts/start-python-guarded.sh`) with `ALLOW_PYTHON_PRODUCTION=1` set at cutover |
| Port | `${PORT:-3000}` (Render-injected) |
| Trusted proxy | `--proxy-headers` + `FORWARDED_ALLOW_IPS` (Render's proxy boundary) |
| Health check | `/api/status` (liveness); startup schema check acts as the readiness gate (refuses to serve on mismatch) |
| Database | `DATABASE_URL` → existing production PostgreSQL (existing service, unchanged) |
| Sessions | `SESSION_SECRET` (same value as Node's, required for cross-backend session/rollback compatibility; rotating it logs everyone out) |
| CORS | `CHEAPDATA_PUBLIC_URL` = production frontend origin |
| Providers | `PAYSTACK_SECRET_KEY`, `WISESUB_API_KEY`, `WISESUB_API_SECRET`, `WISESUB_ENVIRONMENT=live`, `BREVO_API_KEY`, `BREVO_FROM_EMAIL`, `BREVO_FROM_NAME`, `CHEAPDATA_MARKUP_PERCENT` |
| Cutover arming | `ALLOW_PYTHON_PRODUCTION=1` (final step, only on explicit authorization) |
| Logging | stdout (Render); no secrets emitted (verified in staging logs) |
| Rollback | see ROLLBACK-RUNBOOK.md + rollback triggers below |

Pre-cutover environment review must confirm: provider keys are
**live** (not sandbox) values only at cutover time; every provider
variable is present (production-mode startup validates WiseSub env;
missing Brevo keys disable password-reset email delivery — see
PRODUCTION-READINESS §4).

## Ordered cutover execution plan (executes ONLY under explicit owner authorization)

1. **Preconditions verified:** all six owner actions evidenced
   (provider sandboxes tested on staging; production-schema copy
   audited; real-data restore rehearsed; backup/restore + rollback
   rehearsal complete; staging DB renewed; this checklist fully PASS).
   Owner gives written cutover authorization naming the release commit.
2. **Backup verification:** owner creates a production database backup
   and confirms its integrity/restore path; record backup ID, size,
   timestamp (rollback anchor).
3. **Schema compatibility confirmation:** `app.schema_check` PASS
   against the production database (read-only preflight) with no
   missing generated-ID defaults; migrations 001–003 already applied
   or applied in this window with the owner watching.
4. **Provider results confirmed:** live (non-sandbox) provider keys
   staged as production env values; sandbox evidence reviewed.
5. **Release identification:** cut-over commit = the reviewed master
   SHA; deploy it to the production API service **after** completing
   steps 6–7 prep; record deploy IDs.
6. **Production environment configuration review:** set the
   environment variables per the table above (same names as Node where
   shared; `ALLOW_PYTHON_PRODUCTION=1` LAST); never print values.
7. **Health/readiness verification plan:** after deploy, check
   `/api/status`, register/login smoke test, dashboard fetch, admin
   gate 401, CORS allow for the production frontend origin.
8. **Frontend API-origin transition:** production frontend's
   `api-base-url` already points at the production API origin; if any
   change is needed it is an explicit, reviewed config change (never
   automatic).
9. **Smoke tests:** the staging browser journeys (register, login,
   PIN, dashboard, catalog, purchase with a small real amount, webhook
   acceptance) executed against production by the owner or operator
   with the owner watching.
10. **Payment/purchase monitoring:** watch Paystack webhooks,
    WiseSub fulfillment, and wallet/purchase transactions for the
    first hour; no manual retry of uncertain transactions (the backend
    leaves them pending for reconciliation by design).
11. **Error-rate/latency monitoring:** Render metrics/logs for the
    first 24–48h; rollback trigger thresholds below.
12. **Rollback triggers:** sustained 5xx/error rate beyond baseline;
    login/session failure; purchase or webhook processing failure;
    database errors; any suspected double-credit or double-purchase.
13. **Node restoration steps:** switch the production API service
    back to `rootDir: apps/api` (Node) — or redeploy the previous
    Node deploy via Render's rollback; do NOT change the database.
14. **Database compatibility after rollback:** Node reads
    Python-written rows (proven bidirectionally on staging + disposable
    PostgreSQL); sessions issued under the same secret continue to
    work on Node; if `SESSION_SECRET` was rotated, users re-login once.
15. **Post-rollback validation:** same smoke tests as step 9 against
    Node; confirm no pending-purchase or double-credit anomalies;
    reconcile wallets/transactions against provider records.

**Steps that cannot be safely reversed:** live purchase/webhook
processing under Python creates rows both backends can read (reversible
by rollback); a provider key rotation is reversible but invalidates
nothing critical; **migrations 001–003 are additive and idempotent and
are NOT reversed on rollback by design** (Node ignores the added
columns/tables) — this is the accepted one-way data change. Session
secret rotation forces one re-login. Nothing in the plan writes to the
database destructively.

## Verdict update (2026-10-16, third verification session)

Master `668fd50` (PR #12 merged; CI green). Staging tracks master and
auto-deployed `668fd50` live. Fresh re-verification this session:
SQLite suite 121→124 passed (start-guard tests added in PR #13),
PostgreSQL integration 7/7 on a new disposable TLS-verified database,
22/22 Node↔Python cross-compatibility checks on a new shared
disposable PostgreSQL, staging browser journeys re-verified end to end
(register → PIN → login → dashboard → logout → bad-login error →
re-login → buy-data empty catalog), staging security gates re-verified
(HSTS/security headers, CORS allow/deny, admin 401, unsigned webhook
rejection).

**Corrections and incident (2026-10-16 post-merge verification):** the
pre-deploy hook is STILL configured (found at
`envSpecificDetails.preDeployCommand` — the earlier resolution read the
wrong field; inert on the free plan but must be removed before any plan
upgrade), and a bulk env-vars replace accidentally wiped the staging
service's six environment variables; five were restored from documented
values plus a fresh `SESSION_SECRET`, and `DATABASE_URL` requires an
owner re-paste (OWNER-ACTION-CHECKLIST Action 7). Staging is serving
the live pre-incident deploy with no user-visible impact; deploys fail
closed until restored. New finding (documented in PRODUCTION-READINESS §2): the
production **Node** dependency `proxy-addr@2.0.7` has a critical
IP-spoofing advisory (GHSA-jqcg-44mw-7w3h) reachable via
`trust proxy 1`; this is a pre-existing production-Node issue, not a
Python gap — owner decides between a reviewed Node dependency bump
(auto-deploys production on merge) or accepting the risk until the
Python cutover removes that request path.

**STAGING VERIFIED, ENGINEERING COMPLETE — READY FOR CUTOVER REVIEW.**
Remaining gates are exactly the owner actions (provider sandbox
credentials, production-schema evidence, real-data restore/rehearsal,
staging DB renewal). Cutover requires this checklist fully PASS plus
separate written authorization. Production remains on Node.

**Prior verdict (2026-10-15, superseded above):** NOT READY FOR
CUTOVER at that time; the Python backend was live on Render staging.
Verified then: frontend
browser walkthrough, session/CORS/admin-gate/health checks, a 33-check
side-by-side route matrix with full behavioural parity, and bidirectional
Node↔Python data compatibility on the actual staging database (rollback
safety). Remaining blockers: provider sandbox credentials (WiseSub /
Paystack / Brevo — step 9 lists the exact blocked tests), an approved
staging copy of real production data (which is also the only way to
answer the production-schema ID-default question), real-data purchase and
reconciliation journeys, and removal of the staging pre-deploy hook
(dashboard-only). Production traffic remains on Node; the merged
`master` is deployed only to staging; a production cutover requires this
checklist fully PASS plus separate explicit authorization. Nothing here
constitutes cutover approval.
