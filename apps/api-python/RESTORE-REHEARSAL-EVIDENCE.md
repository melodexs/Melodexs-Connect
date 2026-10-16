# Isolated Production-Data Restore Rehearsal — Evidence

**Performed:** 2026-10-16 (UTC), using the Neon access the owner provided.
**Scope:** prove that the production database can be backed up read-only and
restored into an isolated environment, that the Python backend boots and
operates on the restored data after the cutover migrations, and that no
production system is touched at any point.

## Environment and safety

- Source: the live production database (Neon, read-only access through a
  dedicated `mcx_audit_reader` role created for this work). No writes, no
  DDL, no credentials changes on production. Existing production
  credentials were never read.
- Restore target: a disposable PostgreSQL database inside the agent's
  sandbox (`mcx_rehearsal`), reachable only from the sandbox. **Deleted
  after the rehearsal** together with the local backup file, which
  contained real user data.
- Production traffic, configuration, and data: untouched throughout.

## Procedure and measured results

1. **Read-only logical backup.** All rows of `users`, `data_plans`,
   `transactions`, `sessions` (and the leftover `playing_with_neon`
   table) were read over an HTTPS connection: **8 + 176 + 32 + 1 + 10 = 227 rows**.
   Serial sequence positions (`users_id_seq`, `transactions_id_seq`) were
   captured alongside.
2. **Restore.** Schema applied from the Python backend's reviewed base
   schema, then the 227 rows loaded. Result: **227/227 rows restored,
   zero errors, counts identical to source** (8 users, 176 plans,
   32 transactions, 1 session).
3. **Startup guard verification (before migrations).** Booting the Python
   backend in production mode against the restored, un-migrated
   production schema **correctly failed closed**: the PostgreSQL schema
   check reported every missing migration artifact (migrations 001–003)
   and refused startup. This is exactly the intended cutover safety
   behavior on real production data.
4. **Cutover-migration rehearsal.** Migrations `001`, `002`, `003` were
   applied **in order to the isolated copy only**: all succeeded, and the
   schema checker reported **zero incompatibilities** afterwards. All
   restored rows intact post-migration.
5. **Production-mode boot on restored data.** The Python backend booted
   in production mode (NODE_ENV=production, PostgreSQL, live WISESUB
   validation) against the migrated restored copy.
6. **End-to-end verification on restored data** (HTTP smoke):
   - `/api/status` — 200.
   - Register a rehearsal user — success (id 9 continues the serial
     sequence past the restored ids, proving sequence continuity).
   - Login — signed, HttpOnly, `Secure; SameSite=none` session cookie
     issued (correct production cookie attributes; over HTTPS as in
     staging/production).
   - `/api/session`, `/api/user/9` — authenticated reads work.
   - Purchase-PIN set/verify — success; wrong PIN rejected with 401.
   - Admin gate — non-admin denied (403) on `/api/admin/users`.
   - Cross-user transaction read attempt — correctly blocked with 403
     (users may only read their own history).
   - Logout — session revoked; `/api/session` reports logged-out.
7. **Cleanup.** Backend stopped, scratch database dropped, backup file
   containing real user data deleted from the sandbox. Rehearsal time for
   backup + restore + migration + boot at the current data volume
   (227 rows): **under one minute end-to-end**; at this scale the real
   cutover's restore time will be dominated by provider endpoint
   warm-up (seconds), not data transfer.

## Findings

1. **PASS — restore integrity.** Row-for-row restore with zero errors;
   sequences continued correctly (new user id = 9 after restored 1–8).
2. **PASS — startup guard on real production data.** The guard refuses to
   boot against the un-migrated production schema and passes immediately
   after the three reviewed migrations.
3. **PASS — Python backend fully operational on restored production data**
   (auth, sessions, PIN, authorization, admin gate, revocation).
4. **OPERATIONAL REQUIREMENT (new, important): the restored production
   catalog is invisible to `/api/data-plans` until a WiseSub catalog sync
   runs.** The production `data_plans` rows predate migration 002: their
   `source`/`category` columns are NULL, and the route (correctly) serves
   only `source='wisesub'`, categorized, provider-available plans. After
   cutover, an admin must run `POST /api/admin/data-plans/synchronize`
   (with live WiseSub credentials) before any data-purchase journey
   works. **This step is now explicit in the CUTOVER-CHECKLIST.**
5. **Note:** the legacy `playing_with_neon` experimentation table restores
   harmlessly; owner may drop it at cutover.

## Conclusion

The backup→restore→migrate→boot→verify chain succeeds against real
production data with zero discrepancies. This closes the
"backup/restore rehearsal" owner gate (Actions 3–4 of
OWNER-ACTION-CHECKLIST) at the rehearsal scope currently possible,
with the catalog-sync requirement folded into the cutover plan.
