# Cutover approval package — 2026-10-16

This document consolidates every verification performed for the Python
backend migration and states exactly what remains before production traffic
moves from the Node backend (`apps/api/`) to the Python backend
(`apps/api-python/`). It is the review artifact for the cutover decision.

Companion evidence: [PRODUCTION-READINESS.md](PRODUCTION-READINESS.md),
[CUTOVER-CHECKLIST.md](CUTOVER-CHECKLIST.md),
[RESTORE-REHEARSAL-EVIDENCE.md](RESTORE-REHEARSAL-EVIDENCE.md),
[SANITIZED-PRODUCTION-SCHEMA-EVIDENCE.md](SANITIZED-PRODUCTION-SCHEMA-EVIDENCE.md),
[STAGING-TEST-EVIDENCE.md](STAGING-TEST-EVIDENCE.md).

## 1. Code state (2026-10-16)

- `master` at 25318c1, CI green (124 passed / 7 skipped at last master run;
  locally re-verified below).
- Open PRs, all `mergeable_state=clean`, zero conflicts:
  - **PR #18** — pin `ip-address >= 10.7.1` (GHSA-h3mg-xc3c-68pw ReDoS).
    Verified non-exploitable in current deployment; patched as
    defense-in-depth with a regression workflow.
  - **PR #19** — 36 mocked provider-flow tests (Paystack, WiseSub, Brevo);
    single new test file, no production code touched.
  - **PR #20** — readiness matrix 2026-10-16 evidence addendum (docs).
  - **PR #21** — tolerate colliding WiseSub package codes with last-wins
    dedupe (data-plan sync robustness), with regression tests.

## 2. Test matrix (re-verified 2026-10-16)

| Suite | Result |
|---|---|
| Python full suite, external scratch SQLite | **126 passed / 7 skipped** |
| PostgreSQL-gated suite (concurrency + gate), disposable PG 15, TLS `sslmode=verify-full` | **26/26 passed** |
| Provider-flow mocks (Paystack/WiseSub/Brevo, PR #19) on current tree | **36/36 passed** |
| Node smoke suite (`apps/api`), disposable scratch PostgreSQL | **passed** |
| Cross-backend compatibility matrix (Node↔Python sessions/PIN) | **22/22 passed** (2026-10-16 evidence) |

Coverage notes for the mocked provider flows (PR #19): Paystack
initialize/verify with out-of-range amounts, tampered payments, non-success
statuses, timeout, webhook signature enforcement, replay idempotency,
foreign-event rejection; WiseSub success, all unconfirmed outcomes
(pending/timeout/no-reference) kept pending with do-not-retry messaging,
duplicate-purchase blocking, request-id idempotency, validation, price
conflict, and the full reconciliation flow including unrecognized and
failed-without-flag statuses; Brevo unknown recipient, sender/auth payload,
reset-token rotation with replay safety, timeout.

Test protocol (per PRODUCTION-READINESS §7): the full suite runs on scratch
SQLite and the gated files run against an approved disposable PostgreSQL.
Running the whole suite in PG mode is unsupported and produces 18 documented
cookie-transport artifacts (Secure cookies over plain HTTP in the in-process
test client), not backend defects.

## 3. Staging verification (2026-10-16, live)

Python API https://melodexs-connect-api-staging.onrender.com — deployed at
master 25318c1, runtime `python`, branch `master`, no pre-deploy hook.
Frontend https://melodexs-connect-staging.onrender.com.

Live E2E (fresh account): health, all security headers
(`X-Content-Type-Options`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`, HSTS), CORS allow for the
staging frontend origin and deny for foreign origins, register, session
cookie `Secure`+`HttpOnly`+`SameSite`, authenticated profile read,
cross-user profile/transaction access blocked, catalog routes, admin gate
blocks non-admins and anonymous users, logout, session destroyed after
logout, generic 401 on bad credentials, 404 (no stack traces) on unknown
routes. **21/21 substantive checks passed.**

Staging database (Neon, Ohio): dedicated `staging_app` role, `staging`
database, distinct from production (`ep-blue-cloud-…` / `melodexs` vs
`ep-wild-night-…` / `staging`); 6 tables present
(`users`, `transactions`, `data_plans`, `sessions`, `data_plan_sync_runs`,
`api_rate_limits`); unique `reset_token_hash` index present; migrations
001–003 applied; startup schema check hard-fails on any missing migration
object. Catalog is intentionally empty until the post-merge WiseSub sync.

## 4. Production (unchanged, Node)

- API service `melodexs-connect-api`: branch `master`, rootDir `apps/api`,
  runtime `node`, live deploy at 25318c1 (2026-10-16), no pre-deploy hook.
  Node smoke suite passes against a disposable PostgreSQL.
- Provider env keys present on production: `PAYSTACK_SECRET_KEY`,
  `WISESUB_API_KEY`, `WISESUB_API_SECRET`, `WISESUB_BASE_URL`,
  `WISESUB_ENVIRONMENT`, `BREVO_API_KEY`, `BREVO_FROM_EMAIL`,
  `BREVO_FROM_NAME`, `DATABASE_URL`, `SESSION_SECRET`, `NODE_ENV`.
- Production schema verified to match the Python backend base schema
  (SANITIZED-PRODUCTION-SCHEMA-EVIDENCE.md); recovery rehearsal restored
  227 production rows into an isolated sandbox with 100% integrity.

## 5. Remaining owner actions (the only blockers)

1. **Provider sandbox credentials** (Paystack / WiseSub / Brevo test keys)
   for non-consumptive real-world testing. Brevo sandbox header
   (`"X-Sib-Sandbox": "drop"`) is confirmed by docs as the non-consumptive
   path; environment configuration is ready for secure injection.
2. **Merge authorization for PRs #18, #19, #20, #21** (all clean, CI green).
3. **Cutover authorization** — after (1)–(2) and a real-world provider
   sandbox pass, switch the production service to `apps/api-python`
   (runtime `python`, staging-identical start command), then run the
   post-cutover WiseSub catalog sync (PR #21 makes it collision-tolerant).

Nothing in this package modifies production. Production stays on Node until
the owner explicitly authorizes cutover.
