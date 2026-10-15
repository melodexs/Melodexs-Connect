# MELODEXS CONNECT — Python Backend Production-Readiness Matrix

Status report as of 2026-10-15 (second verification session). Classifies
every capability of the Python backend (`apps/api-python/`) against the
production Node backend (`apps/api/`) using four statuses:

- **PASS** — supported by concrete test or deployment evidence
- **FAIL** — a known defect or failed requirement
- **BLOCKED** — requires external access, credentials, or owner action
- **NOT TESTED** — no sufficient evidence exists

**Overall verdict: NOT READY FOR CUTOVER REVIEW.** Application parity,
security, database compatibility, and reliability are in strong shape,
but the acceptance gate requires verified provider workflows
(Paystack / WiseSub / Brevo sandbox), an authorized production-data
check, and explicit owner acceptance of remaining limitations. Those are
BLOCKED on owner action, not on engineering work.

Snapshot: master `8fd1e5c`; PR #8 (evidence docs), PR #9 (CI), PR #10
(security hardening) open and cleanly mergeable. Production remains on
Node.js and was not modified.

---

## 1. Node/Python functional parity — PASS

Verified by a 33-check side-by-side route matrix on a shared disposable
PostgreSQL (both backends live simultaneously) plus bidirectional
cross-backend login on the actual staging database (STAGING-TEST-
EVIDENCE.md, sections A and B).

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

## 7. CI & automated testing — PASS

- Suite: **121 passed, 7 skipped** (after PR #10's 9 new tests).
- The 7 skips are the PostgreSQL integration tests, opt-in by
  validated-connection gate (they run as 7/7 when explicitly enabled
  against an approved PostgreSQL — last verified 2026-10-15).
- CI: GitHub Actions workflow added (PR #9, verified green on its own
  branch): full suite on every PR/master push touching
  `apps/api-python/`, scratch SQLite outside the repo, in-repo DB
  guard, `git diff --check`.

## 8. Render deployment readiness — PASS for staging; production unchanged

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
- Staging pre-deploy migration hook: BLOCKED on dashboard-only owner
  action (Render API cannot clear it — reconfirmed).
- Staging PostgreSQL expires **2026-11-14** — re-provisioning required
  before then if staging must persist.

## 9. Backup & rollback — PARTIAL

- ROLLBACK-RUNBOOK.md (this PR) documents the full procedure with
  tested/untested distinctions.
- Tested (staging/disposable): application-layer rollback cycle,
  bidirectional data compatibility, no schema drift.
- NOT TESTED: production backup/restore rehearsal, Render one-click
  deploy rollback endpoint, provider webhook replay across a switch.

## 10. Owner actions required (the complete blocker list)

| # | Blocker | Required from owner | Unblocks |
|---|---|---|---|
| 1 | Provider sandbox credentials | `PAYSTACK_SECRET_KEY`, `WISESUB_API_KEY`, `WISESUB_API_SECRET`, `BREVO_API_KEY` + `BREVO_FROM_EMAIL` on staging (test/sandbox values) | All live provider tests; catalog sync; end-to-end purchase; reset email |
| 2 | Production schema evidence | Approved sanitized production-schema copy or authorized equivalent | ID/default compatibility check (last pre-cutover data unknown) |
| 3 | Real-data staging copy | Approved production backup restored to staging | Real-data preflights, purchase history verification |
| 4 | Staging pre-deploy hook | Remove via Render dashboard | Clean staging deploys |
| 5 | Staging database expiry | Re-provision/extend before 2026-11-14 | Continued staging verification |
| 6 | Rollback rehearsal approval | Isolated-environment backup/restore rehearsal | Rollback confidence for cutover approval |

## 11. Decision

**NOT READY FOR CUTOVER REVIEW.** Once blockers 1–3 are satisfied (4–6
in parallel), the remaining verification work is bounded: run the live
provider flows, the production-copy schema check, and the real-data
preflights; re-run the browser journeys with a synced catalog; then
this matrix can be re-assessed toward READY FOR CUTOVER REVIEW.
Production remains on Node.js; no cutover has been performed or
approved.
