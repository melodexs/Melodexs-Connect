# MELODEXS CONNECT — Production Rollback Runbook (Python → Node)

Scope: returning production to the existing Node.js backend
(`apps/api`) after a Python backend (`apps/api-python`) has served
production traffic, including data, session, and payment-provider
considerations.

This runbook is operational documentation. It has **not** been executed
against production; every step states which parts are verified by
staging evidence and which remain untested (see *Evidence basis* at the
end). It must be rehearsed on staging or an isolated environment before
a real cutover is attempted.

---

## 1. Rollback trigger criteria

Declare a rollback when any of the following is observed after a Python
cutover:

- Error rate or 5xx rate materially above the Node baseline.
- Login/session failures beyond the expected one-time re-login window.
- Payment or purchase flows failing or producing inconsistent records.
- Database errors (connection exhaustion, schema-check failures at
  startup, constraint violations).
- Any security-relevant regression (auth bypass, data leak).

Prefer rolling back over debugging in place: the Node backend is known
good for production.

## 2. Restore the Node backend service (application layer)

Current production configuration (verified via the Render API on
2026-10-15): the production API service runs with root directory
`apps/api` and start command `npm start` (Node). A cutover would change
the build/start commands (or switch the service to the Python root); the
rollback is the reverse:

1. In the Render dashboard (or API), set the production API service
   back to the Node configuration:
   - root directory: `apps/api`
   - build command: `npm --prefix apps/api install` (or the exact
     values captured in the pre-cutover configuration snapshot)
   - start command: `npm start`
2. Trigger a deploy and wait for `live`.
3. Render also exposes per-deploy rollback ("Rollback this deploy" in
   the dashboard) for the previous deploy of the same service; this is
   the fastest path if the cutover was a plain redeploy. **This
   specific one-click mechanism has not been exercised** — the staging
   verification used fresh deploys of alternate configurations, not
   the rollback endpoint.
4. Verify the Node runtime is serving: `GET /api/status` → 200 and
   `GET /api/data-categories` → 404 (the route exists only in Python).

**Configuration snapshot rule:** before any cutover, capture the full
production service configuration (root directory, build command, start
command, environment variable *names* — never values) and store it with
this runbook so step 1 is mechanical.

## 3. Restore the frontend API configuration

If the cutover repointed the frontend's API base URL:

1. Restore the previous API base URL in the frontend configuration /
   meta tag (the staging frontend was verified to be driven by an
   `api-base-url` meta tag; production must be re-checked at cutover
   time).
2. Redeploy the frontend service.
3. Hard-refresh and verify the site calls the Node API (browser network
   tab; check the API host on `/api/status`).

## 4. Database compatibility requirements (rollback data safety)

Requirements verified by evidence (2026-10-15):

- **Both backends read the same schema.** Migrations 001–003 are
  additive-only (new columns/tables/indexes). The Node backend ran
  against the fully-migrated staging PostgreSQL with zero errors.
- **Both backends read each other's rows.** On the actual staging
  database: Node logged into a Python-created account, and Python
  logged into a Node-created account and verified a Node-set purchase
  PIN. The same was verified on a disposable PostgreSQL in both
  directions.
- **Node ignores Python-only routes/columns.** The only Python-only
  route is `GET /api/data-categories`; Node returns 404 for it, which
  the frontend must tolerate (see §7).

Requirements NOT yet verified (blocking full confidence):

- The **production** database's ID/identity defaults (Node-era DDL)
  have not been inspected; see the CUTOVER-CHECKLIST blocker #2 for
  the exact pre-cutover check. A rollback does not depend on this, but
  the *cutover* does.
- Production-scale data volume has never been exercised on either
  backend in this configuration.

**During rollback, do NOT run any migration, reset, or destructive
command.** The rollback is application-layer only; the database is
never touched. If the schema was altered by a Python-side mistake,
stop and restore from backup (§5) instead of improvising.

## 5. Database backup and restoration

**Status: NOT TESTED against production.** Before any cutover:

1. Take a verified backup (Render dashboard → PostgreSQL → "Backup
   Now", or `pg_dump` from an authorized environment) and confirm the
   backup artifact's size/timestamp.
2. Restoration must be rehearsed on an isolated database (restore into
   a fresh Render PostgreSQL or a disposable local instance and run the
   schema checker + login smoke test against it). A restoration that
   has only been documented, never performed, must be treated as
   unavailable.

Records created while Python served production are normal rows in the
same tables; after rollback, Node reads them directly (verified
pattern on staging). No data migration is required for rollback.

## 6. Session and cookie behavior after rollback

- Sessions are cookie-based (`connect.sid`-style signed cookies) and
  both backends sign/verify with the same `SESSION_SECRET` algorithm
  and secret. **If the secret is unchanged by the cutover, existing
  sessions continue to work on either backend.**
- If the secret is rotated at any point, all users must log in again
  (observed on staging during an env restore: sessions created before
  the rotation stopped validating). Plan a user notice for this case.
- Session rows are only session-cookie metadata; nothing in them is
  needed for financial records.

## 7. Transactions and provider webhooks across a rollback boundary

- **Transactions created while Python is active** are ordinary rows
  with the same reference format and status values; Node reads them
  (verified on staging). The user's transaction history remains
  visible after rollback.
- **Paystack webhooks delivered during the switch:** the webhook is
  signature-verified by whichever backend receives it; both use the
  same `PAYSTACK_SECRET_KEY`. A webhook delivered while Node is back
  online is processed by Node. Records already credited by Python are
  not re-credited (verify with the duplicate-callback tests applicable
  to each backend at cutover time).
- **WiseSub purchases in flight during the switch** may end in a
  provider-side success that the API did not record. After rollback,
  reconcile pending purchases against provider records (the Python
  admin reconciliation routes exist for this; under Node, use the
  provider dashboard/manual reconciliation). This in-flight gap is
  inherent to any switch and is a reason to schedule cutover in a
  low-traffic window.
- **Frontend contract:** the frontend must tolerate `/api/data-categories`
  returning 404 after rollback (the catalog view falls back to its
  existing plan source). Verify this in the browser after rollback.

## 8. Verification steps after rollback (definition of success)

Rollback is successful only when ALL of the following pass:

1. `GET /api/status` → 200 on the production API (and `/api/data-categories` → 404, proving Node).
2. Registration and login work (smoke account) and the dashboard loads.
3. An existing (pre-cutover) account can log in.
4. A user created **while Python was live** can log in under Node.
5. Transaction history renders, including any purchase made during the
   Python window.
6. Admin routes still reject non-admin users (401/403) and work for the
   owner.
7. Error rate back to baseline for 30+ minutes of observation.
8. A provider reconciliation pass finds no unrecorded successful
   purchases from the Python window.

## 9. Evidence basis (what is proven vs assumed)

**Proven on the real staging database (2026-10-15):** Node serving on
the staging service against the staging PostgreSQL (temporary switch,
restored); bidirectional account/PIN cross-read; no schema drift after
the Node run; deploy/restore cycle via the Render API.

**Proven on disposable PostgreSQL (2026-10-15):** identical behavioral
matrix (33 checks) across all common routes; cross-backend login both
directions; migrations idempotent on re-run; schema checker passes.

**Assumptions (explicitly NOT tested):** production-scale restore
timing; Render's one-click deploy-rollback endpoint; provider webhook
replay across a switch boundary; production frontend configuration
(basis to be captured at cutover time).

## 10. Owner actions required before this runbook can be trusted

- Take and rehearse a production database backup restoration in an
  isolated environment (CUTOVER-CHECKLIST step 1 / blocker #6).
- Provide provider sandbox credentials so webhook/purchase flows can
  be rehearsed end-to-end before cutover (blocker #4).
- Approve a sanitized production-schema copy for the ID-default check
  (blocker #2).
