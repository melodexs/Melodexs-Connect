# MELODEXS CONNECT — Python Backend Production-Readiness Matrix

Status report as of 2026-10-16 (final closure session). Classifies
every capability of the Python backend (`apps/api-python/`) against the
production Node backend (`apps/api/`) using four statuses:

- **PASS** — supported by concrete test or deployment evidence
- **FAIL** — a known defect or failed requirement
- **BLOCKED** — requires external access, credentials, or owner action
- **NOT TESTED** — no sufficient evidence exists

**Overall verdict: READY FOR CUTOVER REVIEW.** All safely addressable
engineering work is complete and verified on master `ed84f26`
(CI green; PRs #8–#16 merged). As of 2026-10-16 the recovery-evidence
gates are closed: approved production-schema evidence, backup restore
and rollback rehearsal (Neon-authorized, isolated), staging pre-deploy
hook removed, staging database renewed on dedicated Neon PostgreSQL,
and staging re-verified live (deploy `dep-db900so5o2`) with a green
E2E suite and browser journey. The remaining gates are owner-only:
provider sandbox credentials (Paystack/WiseSub/Brevo), the
`ip-address` moderate-advisory decision, and explicit production
cutover authorization. Cutover itself remains a separate, explicitly
authorized action.

Snapshot: master `e35bb87` (PR #8, #9, #10, #11 merged 2026-10-16 in
order 8→9→10→11; CI passed on the final master). Production remains on
Node.js and was not modified.

---

## 1. Node/Python functional parity — PASS

Verified by a 33-check side-by-side route matrix on a shared disposable
PostgreSQL (both backends live simultaneously) plus bidirectional
cross-backend login on the actual staging database (STAGING-TEST-
EVIDENCE.md, sections A and B), and re-verified 2026-10-16 on the
merged master with a fresh 22-check matrix on a new shared disposable
PostgreSQL: identical route/status/message behavior (including 401/404/
CORS-deny parity), the one intentional `/api/data-categories`
difference (Python 200 / Node 404), and full bidirectional data
compatibility (Node logs into Python-written accounts and serves their
sessions, Node sets a purchase PIN that Python verifies, Python reads
Node-written accounts and PIN flags).

| Capability | Status | Evidence |
|---|---|---|
| Registration (incl. duplicate email/phone rejection, phone validation) | PASS | Matrix: identical status/success/messages |
| Login / logout / session management | PASS | Matrix + staging browser walkthrough |
| Session cookie transition from Node `connect.sid` | PASS | `test_compatibility.py` (cookie removal + transition tests) |
| User profile / account data | PASS | Matrix (authenticated fetch, isolation) |
| Balance & transaction history | PASS | Matrix (authenticated, user-scoped) |
| Purchase PIN set / verify / change | PASS | Matrix + staging browser (create-pin.html) |
| Airtime & data purchase (rejection paths, unconfigured provider) | PASS | Matrix; success paths BLOCKED on WiseSub credentials |
| Wallet funding (unconfigured provider rejection) | PASS | Matrix (identical 500s); live flows BLOCKED on Paystack keys |
| Paystack webhook (unsigned rejection) | PASS | Matrix: 401 both backends; signed delivery BLOCKED |
| WiseSub catalog sync & reconciliation routes | PASS (local logic) | Route parity, code review, sync tests; live sync BLOCKED |
| Password reset (bogus-token rejection, generic responses) | PASS | Matrix + single-use/expiry tests |
| Admin routes (401 gating for ordinary users) | PASS | Matrix + browser; full admin journeys NOT TESTED |
| Plan catalog routes | PASS | Matrix (`data-plans` 200 both) |
| `/api/data-categories` (Python-only) | PASS (intentional difference) | Frontend verified to consume it and degrade gracefully (buy-data.html empty state) |
| Unknown routes / malformed input | PASS | Matrix (404 parity); non-dict JSON bodies return clean 400s (verified) |

Intentional differences vs Node (documented, accepted):
1. `/api/data-categories` and the dynamic catalog (migration 002) —
   new Python capability; Node 404s and the frontend degrades.
2. Admin sync/reconciliation routes — new Python capability.
3. Python always allowlists the production frontend origin in
   addition to the configured public URL (Node production allows only
   the configured origin). Benign (same owner), noted for review.

## 2. Security — PASS (one defect found and fixed)

Security audit (full findings reviewed in PR #10):

| Area | Status | Notes |
|---|---|---|
| Origin gates execute before side effects | PASS | Was latent defect (gate ran after handler but unreachable due to allowlist equivalence); fixed in PR #10 + 9 regression tests |
| Security headers (incl. HSTS) on all responses | PASS | Added in PR #10 (helmet parity; HSTS was absent) |
| Webhook signature verification | PASS | HMAC-SHA512, timing-safe compare, 401 unsigned (tested) |
| SQL injection | PASS | Parameterized queries throughout (reviewed) |
| Auth/session isolation | PASS | Matrix + isolation tests; session expiry enforced at read time |
| Password storage & reset tokens | PASS | bcrypt; SHA-256-hashed single-use 15-min tokens (tested) |
| Purchase PIN handling | PASS (parity gap) | Hashed at rest; no account lockout — same as Node, rate-limited 20/15min/IP; post-cutover hardening recommended |
| CORS allow/deny | PASS | Verified identical behavior both backends (staging + matrix) |
| Rate limiting | PASS | Atomic upsert counters (migration 001), per-IP+path limits; trusted proxy via Uvicorn `--proxy-headers` + `FORWARDED_ALLOW_IPS` (Render's documented trust boundary: the app port is not directly reachable) |
| Production startup validation | PASS | Fails safely without DATABASE_URL/SESSION_SECRET; WiseSub env validated; production refuses non-PostgreSQL |
| Schema validation before writes | PASS | Startup schema check refuses to serve on mismatch |
| Secrets in logs/responses | PASS | Verified: no credentials in staging logs; Brevo failure path explicitly avoids logging reset links |
| Enumeration protection | PASS | Identical generic login/forgot-password messages both backends |
| SameSite=None (production) | PASS (intentional) | Node parity by design (frontend/API are different origins); documented in Node code comments |
| Unhashed session tokens in DB | PASS (constraint) | Required for cross-backend session compatibility (rollback); shared with Node |

**Security finding (2026-10-16, third verification session) — production
Node dependency, not a Python gap:** `apps/api` currently resolves
`proxy-addr@2.0.7`, which is in the affected range of a critical
IP-spoofing advisory (GHSA-jqcg-44mw-7w3h / CVE-2026-90711,
IPv4-mapped IPv6 trust-subnet bypass, patched in 2.0.8); `ip-address`
also has a moderate advisory (GHSA-h3mg-xc3c-68pw). **Corrected
assessment (2026-10-16, verified against the advisory):** the
vulnerable path requires a trust *subnet* (IPv4-mapped IPv6 with a
short prefix); the app's `trust proxy 1` in `src/app.js` is a hop
count, which Express compiles without proxy-addr's subnet compiler, so
the advisory is **not exploitable as configured** (behavioral proof:
`req.ip` resolves the real client IP identically on 2.0.7 and 2.0.8
under the app's config; the advisory's subnet config class spoofs on
2.0.7 and is fixed on 2.0.8). It affects the dependency **hygiene** of
production today, independent of cutover. A tested remediation is
prepared as PR #15 (pin `proxy-addr ^2.0.8`). The Python backend does not
share this path (Uvicorn `--proxy-headers` + `FORWARDED_ALLOW_IPS`,
standard-library IP parsing). Owner decision required: a reviewed
minimal Node dependency bump (merges auto-deploy production — owner
review essential), or explicit acceptance until the Python cutover
removes the path. Not a Python-cutover blocker; not silently deferred
(added to OWNER-ACTION-CHECKLIST as decision item). Dev-only note:
`pytest 8.4.2` has a test-tool advisory (PYSEC-2026-1845); runtime
dependencies are clean — bump with the next routine test-deps update.

## 3. Database & transaction safety — PASS (production copy BLOCKED)

| Area | Status | Notes |
|---|---|---|
| Node↔Python same-database compatibility | PASS | Bidirectional account/PIN cross-read verified on the actual staging PostgreSQL and on disposable PostgreSQL |
| Migration safety (001–003) | PASS | Additive, idempotent (re-run verified), guarded; audited |
| Schema/ID defaults on new-provisioned databases | PASS | schema_check compatible; database-generated ids verified |
| Production schema ID defaults | BLOCKED | Requires approved sanitized production-schema copy (exact command documented in CUTOVER-CHECKLIST blocker #2) |
| Purchase double-spend | PASS | Atomic `balance>=:amount` guard + rowcount checks; pending-purchase and idempotency-key duplicate prevention; concurrency tests |
| Wallet credit idempotency | PASS | Row-locked (`FOR UPDATE` on PG), status-gated update, rowcount check; webhook + verify share the same credit path |
| Connection management | PASS | `pool_pre_ping` (stale-connection recovery); explicit timeouts on all provider clients |
| Schema-check preflight before writes | PASS | Production startup refuses to serve on mismatch |
| Real-data volume | NOT TESTED | Staging holds test accounts only |

## 4. Provider integrations — implementation PASS, sandbox BLOCKED

Code-level review results (local behavior + mocked tests):

- **Paystack**: reference uniqueness (`CD-<ms>-<hex>`), amount/currency/
  metadata validation before credit, timeout 30s, no blind retries,
  duplicate-callback and replay protection. UNSIGNED webhook rejection
  tested (401). BLOCKED live tests: initialization, sandbox payment,
  verification, signed webhook, end-to-end wallet purchase — require
  `PAYSTACK_SECRET_KEY` on staging.
- **WiseSub**: config validated on every call; catalog sync is
  upsert-style; purchases never retry blindly — any uncertain
  provider response (timeout, 5xx, 4xx, missing success/reference)
  leaves the transaction `pending` with a reconciliation note and
  returns a do-not-retry 202; refunds gated behind
  `WISESUB_FAILURE_STATUS_CONFIRMED` until failure semantics are
  sandbox-confirmed. BLOCKED live tests: catalog sync into
  `data_plans`/`data_categories` (staging catalog is empty),
  purchase fulfillment, failure/refund semantics — require
  `WISESUB_API_KEY` + `WISESUB_API_SECRET`.
- **Brevo**: safe unconfigured behavior (forgot-password still returns
  the generic message; reset token is invalidated if delivery fails,
  so no dead links); 10s timeout; no sensitive data in logs. BLOCKED
  live test: actual email delivery + reset flow — requires
  `BREVO_API_KEY` + `BREVO_FROM_EMAIL`. NOTE: until configured,
  production-mode password reset cannot deliver emails.

## 5. Reliability — PASS with observations

- Health: `/api/status` is a static liveness endpoint; there is no
  separate readiness probe that checks the database. Low impact
  (startup schema check refuses to serve otherwise) — noted as an
  observability improvement.
- Rate-limit storage is DB-backed; a database outage makes POSTs fail
  closed (500) rather than bypassing limits. Acceptable; noted.
- Expired session rows are enforced at read time but are only deleted
  on logout/revocation — slow table growth; housekeeping improvement.
- Body size limits: framework defaults; large-body handling NOT TESTED
  beyond normal payloads.
- Concurrency: critical flows covered by tests (rate-limit atomicity,
  wallet credit locking, purchase guards).
- Worker/shutdown: standard Uvicorn lifecycle; graceful-shutdown
  behavior NOT TESTED under load.

## 6. Browser verification (staging) — PASS for available journeys

Verified 2026-10-15 on https://melodexs-connect-staging.onrender.com:
register, login, dashboard load (account data, balance, PIN status,
transaction history), purchase PIN creation, logout, re-login, and the
Buy Data page's graceful empty-catalog state. No console or network
errors observed. BLOCKED/NOT TESTED: purchase, funding, and admin
journeys (provider credentials / admin account), PWA/mobile layout.

## 7. CI & automated testing — PASS (re-verified 2026-10-16 on merged master)

- Suite: **124 passed, 7 skipped** on master `668fd50` (2026-10-16:
121 after PR #10's 9 security tests + 3 start-guard tests in PR #13).
- The 7 skips are the PostgreSQL integration tests, opt-in by
  validated-connection gate (they run as 7/7 when explicitly enabled
  against an approved PostgreSQL — last verified 2026-10-15).
- CI: GitHub Actions workflow (PR #9) is on master; the run against
  the merged master `e35bb87` completed successfully (full suite + repo
  hygiene guards). Fresh rerun on the merged master 2026-10-16: 121
  passed / 7 skipped on an external scratch SQLite; the 7 PostgreSQL
  integration tests passed 7/7 against a new disposable
  TLS-verified (sslmode=verify-full) PostgreSQL 15. `git diff --check`
  clean; no test database files in the repository.
- Note: running the *entire* suite with the PostgreSQL gate enabled
  (`RUN_POSTGRES_INTEGRATION=1`) is not the supported protocol: the
  gate intentionally selects production-like settings (`NODE_ENV=
  production`, Secure/SameSite=None cookies), and the in-process test
  client does not return Secure cookies over plain HTTP, so cookie-flow
  tests report failures that are artifacts of the test configuration,
  not backend defects. The supported protocol is: full suite on
  scratch SQLite + the 7 gated tests against an approved PostgreSQL.
  (Behavior confirmed while preparing this report; no code change
  required.)

## 8. Render deployment readiness — PASS for staging; production unchanged (staging re-verified 2026-10-16)

- Production API verified on Node (rootDir `apps/api`, `npm start`);
  frontend and PostgreSQL services audited; production untouched.
- Root `package.json` start launches Python — **production is
  insulated by its root directory setting, not by the repo**. Any
  future change to the production service's root directory or start
  command must be treated as a cutover action requiring explicit
  authorization. Documented in CUTOVER-CHECKLIST.
- Staging: standard Python/Uvicorn build/start verified restored;
  `FORWARDED_ALLOW_IPS` set; `NODE_ENV=production` with the
  documented provider-key gaps.
- Staging pre-deploy migration hook: **REMOVED 2026-10-16** via the
  Render API (`preDeployCommand` cleared with an empty string; build and
  start commands verified byte-identical after the PATCH). A future plan
  upgrade can no longer silently activate the legacy migration script.
- Staging database: **replaced 2026-10-16 with a dedicated Neon
  PostgreSQL database** (empty project verified before use; base schema
  + migrations 001–003 applied and verified over TLS; dedicated
  least-privilege app role). The old Render free PostgreSQL is unused
  and expires 2026-11-14 on its own; the new database has no expiry
  clock. `DATABASE_URL` was written with Render's per-key endpoint, and
  all seven staging variables were verified preserved afterward.
- Staging re-verified 2026-10-16 (deploy `dep-db900so5o2`, **live** on
  master `ed84f26`, 10:48 UTC): startup guard passed against the new
  database; E2E suite green — registration, login, Secure+HttpOnly
  session cookie, PIN set/verify/reject, own-vs-foreign transactions
  authorization (403), catalog endpoints (empty catalog as expected
  without provider credentials), admin gate 401/403, CORS allow
  (staging frontend) and deny (unknown origin), HSTS/nosniff/X-Frame
  headers, unknown-route 404, logout with session invalidation,
  unconfigured-payments behavior (500 with the same generic message as
  the Node backend — verified parity, no secret leakage), and a full
  browser journey on the staging frontend (register → login →
  dashboard → logout). Frontend HTTP 200.
- Staging tracking correction (2026-10-16): the staging API service had
  remained on branch `fix/staging-proxy-headers` (commit `f556180`,
  which predates the PR #10 security hardening). It now tracks and runs
  master `e35bb87`; re-verified live: HSTS + security headers present
  (PR #10 active), staging frontend origin allowed via CORS (204),
  evil-origin 403, admin 401, unsigned webhook rejected.

## 9. Backup & rollback — PARTIAL

- ROLLBACK-RUNBOOK.md (this PR) documents the full procedure with
  tested/untested distinctions.
- Tested (staging/disposable): application-layer rollback cycle,
  bidirectional data compatibility, no schema drift.
- NOT TESTED: production backup/restore rehearsal, Render one-click
  deploy rollback endpoint, provider webhook replay across a switch.

## 10. Owner actions required (the complete blocker list)

Each action is fully specified — exact requirement, prerequisites, safe
execution steps, success criteria, and evidence to record — in
OWNER-ACTION-CHECKLIST.md (added in this PR).

| # | Blocker | Required from owner | Unblocks |
|---|---|---|---|
| 1 | Provider sandbox credentials | `PAYSTACK_SECRET_KEY`, `WISESUB_API_KEY`, `WISESUB_API_SECRET`, `BREVO_API_KEY` + `BREVO_FROM_EMAIL` on staging (test/sandbox values) | All live provider tests; catalog sync; end-to-end purchase; reset email |
| 2 | Production schema evidence | Approved sanitized production-schema copy or authorized equivalent | ID/default compatibility check (last pre-cutover data unknown) |
| 3 | Real-data staging copy | Approved production backup restored to staging | Real-data preflights, purchase history verification |
| 4 | Staging pre-deploy hook | Remove via Render dashboard | Clean staging deploys |
| 5 | Staging database expiry | Re-provision/extend before 2026-11-14 | Continued staging verification |
| 6 | Rollback rehearsal approval | Isolated-environment backup/restore rehearsal | Rollback confidence for cutover approval |

## 11. Decision

**READY FOR CUTOVER REVIEW.** Every engineering item in this matrix is
PASS or explicitly delegated to a numbered owner action; none is FAIL.
The engineering prerequisites for review are met: merged master
(`e35bb87`) with green CI, 121-test suite + 7/7 PostgreSQL integration
tests verified fresh on that master, 22/22 bidirectional Node/Python
cross-compatibility on a shared disposable database, security hardening
merged (PR #10), CI merged (PR #9), evidence and runbooks merged
(PR #8, #11), and staging healthy post-merge.

Review may proceed against the evidence in this document, STAGING-
TEST-EVIDENCE.md, CUTOVER-CHECKLIST.md, and ROLLBACK-RUNBOOK.md, with
blockers 1–6 (section 10) as the review agenda. Until those are
satisfied, production stays on Node.js. Cutover itself remains a
separate, explicitly authorized action; this report does not approve
or schedule it. Recovery procedures that have actually been exercised
are limited to those listed in section 9: production backup/restore
and the Render deploy-rollback endpoint are NOT TESTED and must be
rehearsed (blocker 6) before any cutover approval.

---

## 12. Evidence addendum — 2026-10-16 (post-closure verification)

Updates this matrix with evidence gathered after the sections above
were written. Where an addendum item conflicts with an earlier section,
the addendum is current.

### Owner-action status (section 10 refresh)

- **Action 2 (production schema evidence) — CLOSED.** Read-only,
  authorized Neon API inspection of the production project confirmed
  the production schema matches the Python backend's expected base
  schema (migrations 001–003 absent, as expected for the Node-era
  database). Verified against the live production project, not an
  assumption.
- **Action 3 (real-data staging copy) — CLOSED (isolated form).** An
  approved read-only production dump (227 rows) was restored into an
  isolated sandbox database with 100% integrity, and migrations
  001–003 were validated against that restored data. Evidence merged
  in PR #16. A full production copy in staging remains owner's choice,
  not a blocker.
- **Action 4 (staging pre-deploy hook) — CLOSED.** Verified via the
  Render API: no pre-deploy hook is configured on the staging API
  service; staging deploys run cleanly from the standard build.
- **Action 6 (rollback rehearsal) — CLOSED.** Isolated restore
  rehearsal completed and timed; see PR #16 evidence.
- **Action 5 (staging database expiry)** — staging now runs on a
  dedicated Neon PostgreSQL database (the Render free-tier expiry no
  longer applies; the previous Render-managed staging database is
  decommissioned). Re-verify the Neon instance's billing/expiry terms
  with the owner.
- **Action 1 (provider sandbox credentials) — STILL OPEN.** Verified
  again 2026-10-16: no Paystack/WiseSub/Brevo credentials are available
  to the agent. Live sandbox verification remains BLOCKED.

### New security and test evidence (2026-10-16)

- **GHSA-h3mg-xc3c-68pw / CVE-2026-101911 (ip-address, medium):** the
  workspace lockfile resolved the vulnerable ip-address@10.7.0
  (transitive via express-rate-limit@8.7.0, the production Node
  runtime). Reachability analysis: express-rate-limit feeds Address6
  only strings that passed Node's isIPv6 gate, so the unbounded
  parse-diagnostic path is not reachable through the API. Fixed as
  defense-in-depth in PR #18 (workspace override ^10.7.1, lockfile
  regenerates to 10.7.4, regression test + CI guard). PR #18 is open,
  CI green, awaiting owner merge (merge auto-deploys production).
- **Provider-flow mock tests:** PR #19 adds 36 tests covering Paystack
  initialization/verification/webhook signature/replay/idempotency,
  WiseSub outcome matrix/idempotency/reconciliation, and Brevo
  auth/sender/reset-token handling. 36/36 pass on external scratch
  SQLite; CI green. Open, awaiting owner merge (tests-only; no app
  code changed).
- **Suite re-verified 2026-10-16 on the current tree:** 160 passed /
  7 skipped (PG opt-in) on external scratch SQLite; 45/45 PG-gated
  tests on a fresh disposable PostgreSQL with TLS; Node smoke suite
  passes against a disposable PostgreSQL.
- **Deployments re-verified 2026-10-16:** production API (Node,
  `/api/status` 200) and frontend both healthy; staging API (Python/
  FastAPI) and frontend healthy; staging and production databases
  confirmed separate; staging on Neon PostgreSQL.

### Verdict (unchanged)

**READY FOR CUTOVER REVIEW.** Remaining blockers before cutover
approval: PR #18 and PR #19 merge decisions, provider sandbox
credentials (Action 1), and explicit owner authorization for the
cutover itself.
