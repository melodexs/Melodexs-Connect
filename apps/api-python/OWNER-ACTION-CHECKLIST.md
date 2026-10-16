# MELODEXS CONNECT — Owner Action Checklist (Cutover Review Blockers)

Actionable checklist for the six owner actions listed in
PRODUCTION-READINESS.md §10. None of these can be completed by the
agent without owner credentials, approval, or dashboard access; each
entry states the exact requirement, the safe execution steps, the
success criteria, and the evidence to record. **Nothing here touches
production.** Production stays on Node.js; every action runs against
sandbox providers, disposable databases, or the isolated staging
environment.

Environment state as of 2026-10-16:

- Master: `e35bb87` (PRs #8–#11 merged; CI green).
- Staging API now tracks master and is deployed at `e35bb87`
  (previously it ran `f556180`, which predates the PR #10 security
  hardening; corrected in this session).
- Staging PostgreSQL: `dpg-db8l9ju89jmc73brjgfg-a`, free tier,
  expires **2026-11-14**.

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

## Action 2 — Approved sanitized production-schema evidence

**Exact owner requirement:** owner approval to export the production
PostgreSQL **schema only** (no data), executed by the owner or an
explicitly authorized operator using the command already documented in
CUTOVER-CHECKLIST (blocker #2). The agent must never connect to the
production database without this authorization.

**Prerequisites:** production healthy; `pg_dump --schema-only`
connectivity from an owner-approved environment.

**Safe execution steps:**
1. Owner runs the documented schema-only export command against the
   production PostgreSQL.
2. Owner shares the output file (or its hash plus a review call).
3. Agent runs the schema_check parity suite and the ID/default audit
   against that schema offline in the sandbox — production is never
   touched.
4. Any drift found is resolved by a new reviewed, idempotent migration
   (the 001–003 pattern), never by editing production directly.

**Success criteria:** schema_check passes against the exported schema;
ID/defaults match the migration expectations; drift (if any) resolved via
reviewed migration and re-audited.

**Evidence to record:** the sanitized DDL (or hash) with approval note,
schema_check output, audit result, updated CUTOVER-CHECKLIST status.

---

## Action 3 — Approved production backup restored into isolated staging

**Exact owner requirement:** owner approval to create a **backup** of the
production database and to restore it **only into the isolated staging
PostgreSQL**. Reading production via a backup is authorized; writing to
production is not, and no step here writes to production.

**Prerequisites:** Actions 2 (schema evidence) done or in parallel; a
backup capability on the production PostgreSQL plan (Render dashboard
backup or owner-run `pg_dump` to a private location).

**Safe execution steps:**
1. Owner creates the production database backup (dashboard or `pg_dump`).
2. Owner uploads the backup to the staging PostgreSQL (or provides a
   signed private link to the agent, who restores via the Render
   staging database connection — staging only).
3. Agent runs the real-data preflights on staging: startup schema check,
   row counts by table, purchase-history integrity, session/PIN
   cross-backend checks, and a read-only review for PII handling rules
   (staging must not be shared publicly afterward).
4. Staging is flagged as "contains production data" until wiped.

**Success criteria:** restore completes; schema check passes; counts and
histories reconcile with owner expectations; no writes to production at
any point; staging marked and later wiped or renewed.

**Evidence to record:** backup ID/size/timestamp, restore confirmation,
preflight outputs, and the staging-data handling note.

---

## Action 4 — Backup/restore and rollback rehearsal

**Exact owner requirement:** approval to rehearse the recovery procedures
in ROLLBACK-RUNBOOK.md against disposable/staging infrastructure
(can be combined with Action 3's restored data). No production systems
are involved.

**Prerequisites:** Action 3 complete (or a representative dataset);
staging healthy; a maintenance window on staging (it will be redeployed
repeatedly).

**Safe execution steps:**
1. Exercise the documented Python→Node application-traffic rollback on
   staging using the service-swap procedure (proven once on 2026-10-15;
   repeat with real-data restore).
2. Exercise the Render deploy-rollback endpoint on the staging service
   (restore previous deploy) and record timings.
3. Exercise one full cycle: rollback to Node → verify sessions/logins →
   roll forward to Python → verify.
4. Document measured timings and any deviations in the runbook.

**Success criteria:** both rollback directions complete with data
intact; timings recorded; runbook updated from "NOT TESTED" to
"exercised" for the rehearsed procedures.

**Evidence to record:** rehearsal log with timestamps, deploy IDs both
directions, verification outputs, updated ROLLBACK-RUNBOOK.md.

---

## Action 5 — Remove the staging pre-deploy migration hook (Render dashboard)

**Exact owner requirement:** Render **dashboard** access by the owner.
The hook was created through the dashboard; the API's `preDeployCommand`
reads `None` as of 2026-10-16, so the owner should confirm in the
dashboard whether it is still configured — the API cannot reliably
reflect or clear dashboard-managed settings for this service.

**Prerequisites:** none; 30-second check.

**Safe execution steps:**
1. Owner opens the staging API service in the Render dashboard and
   checks Settings → Pre-Deploy Command (and Build section).
2. If a pre-deploy command/migration hook is present, clear it.
3. Trigger one redeploy and confirm the deploy pipeline has no
   pre-deploy phase.

**Success criteria:** a clean staging deploy with no pre-deploy step and
no schema drift after deploy.

**Evidence to record:** a screenshot (or the deploy log) showing the
pipeline without a pre-deploy phase, and the deploy ID.

---

## Action 6 — Staging PostgreSQL renewal or replacement before 2026-11-14

**Exact owner requirement:** owner decision and dashboard action — the
current agent API key cannot manage Render database instances (the
databases endpoint is not accessible with it). The free-tier staging
PostgreSQL (`dpg-db8l9ju89jmc73brjgfg-a`) is deleted at expiry on
**2026-11-14**, taking all staging verification data with it.

**Prerequisites:** decision on keeping staging beyond 2026-11-14
(recommended, since cutover review requires it).

**Safe execution steps (owner chooses one):**
- Option A — upgrade the staging PostgreSQL to a paid instance in the
  dashboard (data retained), then confirm the staging API still connects.
- Option B — before expiry: export current staging data (optional, test
  accounts only), let the agent provision a fresh free-tier instance via
  API (or owner does it in the dashboard), update the staging API's
  `DATABASE_URL`, re-run the idempotent base schema + migrations 001–003,
  and re-run the staging verification suite (register/login/PIN/session
  walkthrough, CORS, gates).

**Success criteria:** staging PostgreSQL active beyond 2026-11-14 with the
schema applied and verification green, or a deliberate written decision to
retire staging.

**Evidence to record:** new database ID and expiry date, migration
re-apply log, re-verification results, updated STAGING-DEPLOYMENT-RENDER.md.

---

## Suggested order

1. **Action 5** (minutes, unblocks clean staging deploys for everything
   that follows).
2. **Action 1** (provider sandboxes — the largest block of untested
   behavior).
3. **Action 6** (renew staging DB before 2026-11-14 so Actions 1–4
   evidence persists).
4. **Action 2** (schema evidence), then **Action 3** (real-data restore),
   then **Action 4** (rehearsal) — these three form the recovery-evidence
   package.

Once Actions 1–4 are evidenced and 5–6 confirmed, PRODUCTION-READINESS.md
can be re-assessed and cutover scheduled **only with explicit owner
authorization**. Nothing in this checklist is a cutover step.
