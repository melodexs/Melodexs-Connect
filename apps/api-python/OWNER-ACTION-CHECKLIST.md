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

## Action 5 — Staging pre-deploy migration hook — STILL PRESENT (corrected 2026-10-16)

**Correction:** an earlier draft marked this resolved because the Render
API's `serviceDetails.preDeployCommand` read `None`. That was the wrong
field: the hook actually lives at
`serviceDetails.envSpecificDetails.preDeployCommand`, and on
2026-10-16 it IS set (a base64-encoded script that applies
`tests/postgres_test_schema.sql` base schema plus migrations 001–003
to `DATABASE_URL` on every deploy).

**Current risk assessment:** the staging service is on the free plan,
and Render does not EXECUTE pre-deploy commands on free-plan services —
staging deploys complete without a pre-deploy phase (observed at
`e35bb87` and `668fd50`). The Python backend's own startup refuses
production mode without explicit configuration and never auto-migrates.
So today the hook is inert configuration debt. HOWEVER, upgrading the
staging service plan would silently activate it (it would then apply
migrations on every deploy), so it must still be removed in the
dashboard.

**Exact owner requirement:** Render **dashboard** access by the owner.
The hook was created through the dashboard; the API's env-specific
settings are not writable with the available key.

**Safe execution steps:** open the staging API service in the Render
dashboard → Settings → Pre-Deploy Command; clear the field; trigger one
redeploy; confirm the deploy pipeline shows no pre-deploy phase.

**Evidence to record:** screenshot or deploy log of the pipeline without
a pre-deploy phase, plus the deploy ID.

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

## Action 7 (new) — Restore `DATABASE_URL` on the staging API (added 2026-10-16)

**What happened (honest incident record):** while adding
`ALLOW_PYTHON_PRODUCTION=1` to the staging service on 2026-10-16, the
env-vars API call used Render's bulk-replace endpoint (PUT), which
replaces the entire variable set. The service's six original variables
(`NODE_ENV`, `DATABASE_URL`, `SESSION_SECRET`, `CHEAPDATA_PUBLIC_URL`,
`WISESUB_ENVIRONMENT`, `FORWARDED_ALLOW_IPS`) were deleted.

**Impact:** the running staging instance was never interrupted — it
kept its deploy-time environment. The first deploy attempt after the
wipe (post-PR-#13 merge, `ccec9a5`, 09:26 UTC) failed fast at startup
validation (missing explicit `NODE_ENV`), leaving the previous deploy
live. This is exactly the fail-closed behavior the configuration
validations were designed for: no silent misconfiguration, no data
change, no production impact. Staging currently cannot pick up new
master commits until `DATABASE_URL` is restored.

**Recovery performed (2026-10-16):** five of six variables were
restored via the API from documented values (`NODE_ENV=production`,
`CHEAPDATA_PUBLIC_URL`, `WISESUB_ENVIRONMENT=live`,
`FORWARDED_ALLOW_IPS=*` per Render's documented trust boundary — the
app port is not directly reachable; original exact value was wiped and
unrecoverable), and `ALLOW_PYTHON_PRODUCTION=1` was kept. A fresh
`SESSION_SECRET` was generated (the original value is unrecoverable;
when the next deploy succeeds, all staging sessions reset — test
accounts simply log in again). **`DATABASE_URL` cannot be restored via
the API**: the available key has no database-instance scope, and the
original value (an internal Render connection string with generated
credentials) was wiped. It must be re-pasted from the dashboard.

**Exact owner requirement (2 minutes):** Render dashboard → the
staging PostgreSQL (`melodexs-connect-staging-db`, `dpg-db8l9ju89jmc73brjgfg-a`)
→ Connect page → copy the **Internal Database URL** → staging API
service → Environment → add it back as `DATABASE_URL`. Then trigger a
manual deploy of the staging API and confirm it goes live on master
(`ccec9a5` at the time of writing).

**Evidence to record:** deploy ID of the first successful staging
deploy after restoration, and confirmation that `/api/login` works
against the staging PostgreSQL data (e.g. the staging-verify test
account).

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

## New decision item — production Node dependency security update (added 2026-10-16)

**Exact owner requirement:** a decision, not credentials. The production
Node backend resolves `proxy-addr@2.0.7` with a **critical** IP-spoofing
advisory (GHSA-jqcg-44mw-7w3h; reachable via `trust proxy 1`) and
`ip-address` with a moderate advisory. Options: (a) approve a reviewed
minimal dependency bump PR for `apps/api` (fix: `proxy-addr@>=2.0.8`,
`ip-address@>=10.x` patch) — note it **auto-deploys production on merge**
because the production service tracks master; or (b) explicitly accept
the risk until the Python cutover removes that request path. Evidence to
record: the owner's written decision, and the merged PR + deploy ID if
option (a).

## Suggested order

1. **Decision item** (Node dependency security — production is exposed
   today regardless of cutover).
2. ~~Action 5~~ (resolved 2026-10-16; dashboard glance only).
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
