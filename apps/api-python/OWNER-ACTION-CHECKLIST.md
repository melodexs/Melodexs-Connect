# MELODEXS CONNECT — Owner Action Checklist (Cutover Review Blockers)

Actionable checklist for the owner actions listed in
PRODUCTION-READINESS.md §10. Each entry states the exact requirement,
the safe execution steps, the success criteria, and the evidence to
record. **Nothing here touches production.** Production stays on
Node.js; every action runs against sandbox providers, disposable
databases, or the isolated staging environment.

**2026-10-16 update:** with the owner-provided Neon API access,
Actions 2, 3, and 4 are now RESOLVED (sanitized production-schema
evidence, isolated restore rehearsal, and the full backup→restore→
migrate→boot rehearsal against real production data). Remaining open
actions: 1 (provider sandbox credentials), 5 (staging pre-deploy hook,
dashboard), 6 (staging PostgreSQL expiry), 7 (staging DATABASE_URL
re-paste), 8 (proxy-addr PR decision).

Environment state as of 2026-10-16 (final update):

- Master: `ed84f26` (PRs #8–#16 merged; CI green).
- Staging API tracks master and is deployed **live** on `ed84f26`
  (deploy `dep-db900so5o2`) after the `DATABASE_URL` restoration.
- Staging PostgreSQL: dedicated **Neon** database (created 2026-10-16;
  no expiry clock). The old Render free database
  `dpg-db8l9ju89jmc73brjgfg-a` is unused and expires 2026-11-14.
- Production: still Node.js, live on `ed84f26` (deploy `dep-db8vpqjk`),
  verified healthy with the proxy-addr@2.0.8 remediation deployed.

---

## Action 1 — Provider sandbox credentials (Paystack / WiseSub / Brevo)

**Exact owner requirement:** test-mode (never live/production) API
credentials, added as environment variables on the staging API service
(`srv-db8lb4bl550s73ee7hig`) or provided to the agent through a secure
secrets channel — never pasted into chat, commits, or docs:

- `PAYSTACK_SECRET_KEY` — a Paystack **test-mode** secret key (`sk_test_…`).
- `WISESUB_API_KEY` and `WISESUB_API_SECRET` — WiseSub partner sandbox
  credentials. Staging already sets `WISESUB_ENVIRONMENT=live`, so the
  partner sandbox keys are required for the staging instance.
- `BREVO_API_KEY` and `BREVO_FROM_EMAIL` — a Brevo API key and a
  verified sender address for test email delivery.

**Prerequisites:** accounts in good standing at each provider; test/sandbox
keys issued; for Brevo, the sender domain verified. No production keys at
any point.

**Safe execution steps (agent performs once credentials are set):**
1. Redeploy staging so the new env vars are loaded.
2. Paystack sequence: initialize `POST /api/fund-wallet` with a small
   test amount; complete the test transaction in the Paystack dashboard;
   verify `POST /api/fund-wallet/verify` credits the wallet exactly once;
   confirm a Paystack-signed `POST /api/paystack/webhook` is accepted and
   replay of the same event is rejected; confirm unsigned webhooks still
   return 401; run one wallet-funded data purchase end to end.
3. WiseSub sequence: run `POST /api/admin/data-plans/synchronize` to
   populate `data_plans`/`data_categories`; read
   `GET /api/admin/data-plans/synchronization`; purchase against a real
   synced plan; confirm a timeout/error leaves the transaction `pending`
   with a do-not-retry 202; record the observed failure semantics so the
   owner can decide the `WISESUB_FAILURE_STATUS_CONFIRMED` flag
   (automated refunds stay disabled until then).
4. Brevo sequence: `POST /api/forgot-password` for a test account, confirm
   the email arrives in a test inbox; complete
   `POST /api/reset-password` with the emailed token; confirm the token
   is single-use and rejected on replay.

**Success criteria:** every step above passes on staging against the real
sandbox providers; wallet credited exactly once per payment; catalog sync
reproducible; reset email delivered and token single-use; no live keys
anywhere; refunds decision recorded.

**Evidence to record:** sanitized request/response logs (references and
IDs only, never keys), transaction/sync IDs, a copy of the email (with
the token redacted), and a new dated section in STAGING-TEST-EVIDENCE.md.
Unblocks: every live provider test in PRODUCTION-READINESS.md §4 and
CUTOVER-CHECKLIST §9–10.

---

## Action 2 — Approved sanitized production-schema evidence — **RESOLVED 2026-10-16**

**Status: DONE.** The owner provided Neon API access (organization key),
authorizing read-only inspection of the production database. A dedicated
audit role (`mcx_audit_reader`) was created via the provider API —
existing credentials were never touched — and the schema was extracted
read-only (catalog queries only; no data rows, no DDL).

**Result:** the production database (Neon `melodexs`, region eu-west-2)
matches the Python backend's base schema **exactly** across `users`,
`data_plans`, `transactions`, `sessions` (columns, types, defaults,
nullability, PKs, unique constraints, FK, index). Migrations 001–003 are
**absent** from production, as required. One non-application table
(`playing_with_neon`, ~10 rows) exists; harmless, owner may drop it at
cutover.

**Evidence:** `SANITIZED-PRODUCTION-SCHEMA-EVIDENCE.md` (this directory).

**Residual note:** the audit role remains on the Neon project for
continued read-only verification; the owner may delete it after cutover.

## Action 3 — Production backup restored into isolation — **RESOLVED 2026-10-16**

**Status: DONE (isolated rehearsal).** With the owner-provided Neon
access, a read-only logical backup of the production database (227 rows:
8 users, 176 data plans, 32 transactions, 1 session, 10 experimentation
rows) was restored into a disposable sandbox PostgreSQL database — a
fully isolated environment with no path to production. Result:
**227/227 rows, zero errors, counts identical to source.** The scratch
database and the backup file (which contained real user data) were
deleted immediately after the rehearsal.

**Evidence:** `RESTORE-REHEARSAL-EVIDENCE.md` (this directory).

## Action 4 — Backup/restore and rollback rehearsal — **RESOLVED 2026-10-16 (rehearsal scope)**

**Status: DONE at rehearsal scope.** The full chain was rehearsed against
real production data in isolation:

1. Read-only backup: 227/227 rows captured.
2. Restore: zero errors, sequence positions carried over (new ids
   continue past restored ids).
3. Startup guard: **correctly refused** to boot against the restored
   un-migrated production schema — the cutover safety behavior proven on
   real data.
4. Cutover migrations 001–003 applied in order to the isolated copy:
   all succeeded; schema checker reported zero incompatibilities.
5. Python backend booted in production mode on the migrated restored
   data; end-to-end smoke passed (login/session, purchase-PIN set and
   verify with wrong-PIN rejection, admin gate, cross-user read
   blocked 403, logout revocation).
6. **New cutover-plan requirement found:** the restored production
   catalog predates migration 002, so `source`/`category` are NULL and
   `/api/data-plans` serves it only after a WiseSub catalog sync
   (`POST /api/admin/data-plans/synchronize`). This step is now
   explicit in CUTOVER-CHECKLIST.

**Still open after rehearsal (owner decisions, not blockers to
preparing the plan):** running the same rehearsal against the staging
service (real data on staging) is optional and not recommended while
staging has no auth isolation; the rollback direction (Python→Node) is
covered by the unchanged Node service and the verified schema
identity — Node can read the migrated database because migrations
001–003 are purely additive.

## Action 5 — Staging pre-deploy migration hook — **RESOLVED 2026-10-16**

**Resolution:** the hook was removed through the Render API, not the
dashboard. `PATCH /v1/services/{id}` accepts
`serviceDetails.envSpecificDetails.preDeployCommand`, and Render's
documented PATCH semantics are "provided fields update (null/empty
unsets), omitted fields unchanged". Sending an empty string cleared
the hook (a `null` value was ignored).

**Verification (2026-10-16, fresh API reads):** after the PATCH,
`envSpecificDetails.preDeployCommand` reads `''` while `buildCommand`
(`pip install -r apps/api-python/requirements.txt`) and `startCommand`
(`python3 -m uvicorn app.main:app --app-dir apps/api-python ...`) are
byte-identical to before. The subsequent manual deploy `dep-db900so5o2`
completed **live** on master `ed84f26` with no pre-deploy phase, and the
application's own startup schema guard passed against the new staging
database. A future plan upgrade can no longer silently activate the
legacy migration script.

**Evidence:** deploy `dep-db900so5o2` (2026-10-16 10:48 UTC, status
live); API-verified service config snapshot before/after.

---

## Action 8 (new) — Decide on the proxy-addr remediation PR (#15)

**Finding (verified 2026-10-16 against the advisory and the code):**
`proxy-addr@2.0.7` in the production Node backend is in the affected
range of CVE-2026-90711 / GHSA-jqcg-44mw-7w3h (Critical 9.1, patched in
2.0.8). The vulnerable configuration class — an IPv4-mapped IPv6 trust
subnet with a short prefix — is **not present**: the app configures
`trust proxy 1` (a hop count), which Express compiles itself without
touching proxy-addr's subnet compiler, and Render's proxy fronting
means the app port is not directly reachable. Behavioral tests on both
versions confirm `req.ip` (the express-rate-limit keying input) is
correct under the app's real configuration on 2.0.7 and identical on
2.0.8; the CVE class spoofs on 2.0.7 and is fixed on 2.0.8.

**Decision required (either is safe):**
1. **Merge PR #15** (pins `proxy-addr ^2.0.8` in `apps/api`) — note this
   AUTO-DEPLOYS production (autoDeploy on master). Risk is minimal: a
   single transitive-dep pin with verified identical behavior; the
   smoke test passes on 2.0.8.
2. **Explicitly accept the residual risk** until the Python cutover
   removes this dependency path entirely, and close the finding as
   "accepted risk, remediated at cutover".

**Evidence to record:** the merge + production deploy ID and health
check, or a written acceptance note.

## Action 7 (new) — Restore `DATABASE_URL` on the staging API — **RESOLVED 2026-10-16**

**What happened (honest incident record):** while adding
`ALLOW_PYTHON_PRODUCTION=1` to the staging service on 2026-10-16, the
env-vars API call used Render's bulk-replace endpoint (PUT), which
replaces the entire variable set. The service's six original variables
(`NODE_ENV`, `DATABASE_URL`, `SESSION_SECRET`, `CHEAPDATA_PUBLIC_URL`,
`WISESUB_ENVIRONMENT`, `FORWARDED_ALLOW_IPS`) were deleted.

**Recovery performed (2026-10-16):** five of six variables were
restored via the API, `ALLOW_PYTHON_PRODUCTION=1` kept, and a fresh
`SESSION_SECRET` generated. The original `DATABASE_URL` (an internal
Render connection string with generated credentials) was unrecoverable
via the API, and the old staging PostgreSQL was additionally due for
deletion on 2026-11-14 — so staging was migrated to a dedicated, empty
**Neon PostgreSQL** database instead (see Action 6). The new
`DATABASE_URL` was written with Render's per-key endpoint
(`PUT /v1/services/{id}/env-vars/DATABASE_URL`), which updates a single
variable and cannot repeat the bulk-replace incident; a follow-up read
confirmed all seven variables present with no other value touched.

**Verified recovery:** first successful deploy after restoration:
`dep-db900so5o2`, **live** on master `ed84f26` (2026-10-16 10:48 UTC).
The startup guard passed against the new database, and a full E2E
suite passed against the live deployment: registration, login,
session cookie (Secure+HttpOnly), PIN set/verify/reject, own-vs-foreign
transactions authorization, catalog endpoints, admin gate, CORS
allow/deny, security headers, unknown-route 404, logout with session
invalidation, plus a browser journey (register → login → dashboard →
logout) on the staging frontend. Staging sessions were reset by design
(fresh database + fresh `SESSION_SECRET`).

**Evidence:** deploy `dep-db900so5o2` (live); env-var list re-read
(7 keys); E2E logs from 2026-10-16 session.

---

## Action 6 — Staging PostgreSQL renewal or replacement before 2026-11-14 — **RESOLVED 2026-10-16 (Option B executed)**

**Resolution:** staging now runs on a dedicated **Neon PostgreSQL**
database provisioned through the authorized Neon API:

- Host project: the existing second Neon project in the owner's org
  (the Ohio/`aws-us-east-2` one; verified empty — 0 tables — before
  use, so no data was overwritten or copied).
- Database: newly created `staging` database on that project's primary
  branch, owned by a newly created dedicated `staging_app` role
  (least-privilege application role; credentials never committed).
- Schema: the Python backend's reviewed base schema plus migrations
  001–003 applied over TLS and verified (6 tables: `users`,
  `data_plans`, `transactions`, `sessions`, `api_rate_limits`,
  `data_plan_sync_runs`; 14 indexes/constraints including
  `uq_users_reset_token_hash`, `uq_transactions_reference`,
  `uq_transactions_user_idempotency`).
- Lifecycle: Neon free-tier autosuspend replaces the Render free-DB
  30-day deletion clock, so there is **no 2026-11-14 expiry** for the
  new staging database.
- The old Render free PostgreSQL (`dpg-db8l9ju89jmc73brjgfg-a`) is now
  unused and unreachable with the available API key. The owner may
  delete it in the dashboard or let it expire on 2026-11-14; it
  contains only staging test accounts.

**Evidence:** fresh API reads of the Neon project/branch/database
inventories; schema verification query output (tables + indexes);
staging deploy `dep-db900so5o2` live; E2E suite green (see Action 7).

---

## Production Node dependency security update — **PARTIALLY RESOLVED 2026-10-16**

- `proxy-addr` (critical, GHSA-jqcg-44mw-7w3h): **RESOLVED.** PR #15
  pinned `proxy-addr@^2.0.8`, merged as `bc1cc25`; the production Node
  service auto-deployed and is **live** on `ed84f26` (deploy
  `dep-db8vpqjk`, 2026-10-16 10:32 UTC). Production verified live
  after the deploy: `/api/status` 200, security headers present,
  generic 401 on bad login, admin gate 401, CORS deny for unknown
  origins.
- `ip-address` (moderate, GHSA-h3mg-xc3c-68pw; transitive via
  `express-rate-limit@8.7.0`, currently 10.7.0): **STILL OPEN — owner
  decision.** Reachable in production through rate-limiter IP parsing
  of `X-Forwarded-For`. Options: (a) approve a minimal reviewed bump PR
  for `apps/api` (auto-deploys production Node on merge, as PR #15
  did), or (b) explicitly accept the moderate risk until the Python
  cutover removes this code path entirely. The prior report's
  recommendation (b + cutover) stands unless the owner chooses (a).

## Suggested order

1. **Action 1** (provider sandboxes — the largest block of untested
   behavior; credentials only the owner can supply).
2. **`ip-address` decision** (a minimal PR awaits approval if chosen;
   otherwise recorded as accepted risk until cutover).
3. Production cutover approval once Action 1 evidence lands — all
   other engineering gates are closed.

Once Actions 1–4 are evidenced and 5–6 confirmed, PRODUCTION-READINESS.md
can be re-assessed and cutover scheduled **only with explicit owner
authorization**. Nothing in this checklist is a cutover step.
