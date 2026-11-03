# Provider sandbox validation: VTpass and MELE DATA (2026-10-18)

This note records what was verified, how the verification is gated, and
what remains intentionally out of scope. No production system was
touched, no real purchase was made, and no live credential was used.

## Safety model (both providers)

- All sandbox tooling is opt-in: it never runs in CI or the default test
  suite, and it never contacts a provider unless explicitly enabled.
- The VTpass client (`app/vtpass_sandbox.py`) is a validation client, not
  a fulfillment adapter: it fails closed unless the base URL is
  `https://sandbox.vtpass.com/api`, so live VTpass credentials can never
  be exercised by mistake through this code path.
- The MELE DATA adapter (`app/provider_meledata.py`) has one base URL for
  live and test traffic (the token selects the mode). With
  `MELEDATA_TEST_MODE=1` it re-checks the provider-reported
  `mode`/`livemode` on the wallet before every purchase and refuses to
  proceed when the mode is live, inconsistent, or unreadable.
- Errors and results are sanitized: credentials never appear in
  exception messages, logs, or returned objects.
- Unknown or malformed provider responses are UNCERTAIN, never mapped to
  a failure or success. Only documented terminal states can finalize a
  transaction, and a provider's own documented refunds are never
  duplicated by the platform.

## VTpass (https://vtpass.com) - sandbox verified

Contract verified against the official documentation AND the live
sandbox environment with the dashboard sandbox keys:

- Base URL `https://sandbox.vtpass.com/api`; GET requests use
  `api-key` + `public-key` headers, POST requests use `api-key` +
  `secret-key`.
- `GET /balance` returns the mock sandbox wallet (verified at
  NGN 2,000,000 mock credit).
- `GET /service-variations?serviceID=...` returns `variation_code`,
  `name`, `variation_amount` (string), `fixedPrice`. Verified serviceIDs:
  `mtn-data`, `glo-data`, `airtel-data`, and `etisalat-data` for 9mobile
  (`9mobile-data` returns code 011 "Service is Not Valid").
- Live catalogs contain DUPLICATE `variation_code` values (e.g.
  `mtn-xtratalk-300`). The client reports these explicitly in
  `VtpassCatalog.duplicate_codes` and never treats an ambiguous code as a
  distinct purchasable product.
- `POST /pay` uses the `phone` recipient field (not the docs'
  `billersCode`). Documented sandbox scenarios, all verified live:
  - `08011111111` successful (code 000, status "delivered");
    the wallet is debited unit price minus a 4% commission.
  - `201000000000` pending (code 000, status "pending").
  - any other number failed (code 016); verified NOT to debit the wallet.
  - `400000000000` "no response": HTTP 200 with an EMPTY body.
  - `300000000000` timeout (transport-level).
- Duplicate `request_id` returns code 014 WITHOUT replaying the original
  response; the only documented recovery is requery.
- `POST /requery` by `request_id`; code 015 for unknown ids; inner status
  "reversed" (code 040) maps to a provider-reversed (refunded) failure.

Mocked contract tests: `tests/test_vtpass_contract.py` (26 tests).
Opt-in live sandbox tests: `tests/test_vtpass_sandbox_live.py`
(9 tests, all passing 2026-10-18). Enable with
`VTPASS_SANDBOX_LIVE_TESTS=1` plus the three sandbox key variables.

## MELE DATA (https://meledata.ng) - partially verified

Contract verified against the developer documentation and live calls
with the mele_test_... token (test mode):

- Single base URL `https://meledata.ng/api/v1/developer`; auth header
  `X-API-Key`.
- `GET /wallet` (NOT `/wallet/` - the trailing-slash form 308-redirects)
  reports balance, currency, and the authoritative `mode`/`livemode`
  flags. The test token reports mode="test", livemode=false, balance
  NGN 1,000,000 (mock).
- `GET /data/plans` (verified live) returns
  `{"status": true, "data": {"plans": [...]}}` with integer `plan_id`
  purchase keys - the adapter was corrected to this envelope; the
  originally-assumed top-level `plans` shape is rejected.
- `GET /data/status?ref=...` (no trailing slash) is the documented
  requery; unowned references return a "not owned by your client" error
  which the adapter treats as unrecognized (never success/failure).
- `POST /data/purchase` takes `network`, 11-digit `phone_number`, int
  `plan_id`, and a `reference` (max 80 chars, idempotent).
- `POST /airtime/purchase` takes the same shape with a minimum amount of
  NGN 100.

KNOWN PROVIDER LIMITATION (2026-10-18): every test-mode purchase attempt
against the test wallet (plans from NGN 110 up) returns HTTP 400
"Insufficient wallet balance." despite the NGN 1,000,000 test balance,
with both the test secret and test public tokens. MELE test purchases
are therefore NOT verified end-to-end. The purchase success/failure/
duplicate-reference paths are covered by mocked contract tests only
(`tests/test_meledata_adapter.py`). Enabling live MELE routing must
wait until the provider confirms test-purchase behavior (support
contact recommended before any live integration).

### Is there an official MELE DATA sandbox? (documented evidence)

No sandbox is documented anywhere on https://meledata.ng/developer/docs.
What the official documentation DOES establish (extracted 2026-10-18):

- ONE base URL serves all traffic; the TOKEN selects the mode. There is
  no sandbox host.
- Tokens carry a mode: the wallet response documents `livemode`
  ("true for live tokens, false for test") and `mode` ("live" or
  "test"), and issued keys are visibly prefixed (`mele_live_...` /
  `mele_test_...`).
- Only `GET /wallet/` and `GET /data/status/?ref=` are labeled
  "Live + test". `POST /data/purchase`, `GET /data/plans` and
  `POST /airtime/purchase` carry NO test-mode label - the docs never
  state that purchases can be simulated with test tokens.
- No documented process exists for issuing test credentials, funding or
  activating a test wallet, or simulating purchases. The error table's
  `400 insufficient_balance` means "Wallet is below the order total."
- Safe purchase-status checks ARE documented: `GET /data/status/?ref=`
  (requery, token-scoped, 404 for other users' references), reference
  idempotency ("Retry with the same reference and you get back the
  original response - no double-debit", max 80 chars, per-token scope)
  and automatic wallet refund on carrier rejection.

Live behavior observed with a test token (read-only requests; the
purchase attempts predate this stricter policy): wallet reports a MOCK
balance (NGN 1,000,000, mode "test", livemode false); the catalog works;
purchases are refused with insufficient_balance. The most likely
explanations (unconfirmed): the purchase path checks a different,
uninitialized balance for test tokens, or test purchases are simply not
implemented server-side. This is a provider question, not a bug we can
fix client-side.

Prepared support inquiry (NOT sent; no account details or keys in it):
1. Does MELE DATA offer an official sandbox/test mode for the Data and
   Airtime purchase APIs, or are test tokens read-only?
2. How are test credentials issued, and how should a developer confirm
   they are in test mode? (We currently rely on the documented
   `mode`/`livemode` wallet fields.)
3. Why does `POST /data/purchase` with a test token return HTTP 400
   "Insufficient wallet balance." although `/wallet/` reports a
   NGN 1,000,000 test balance?
4. Can purchase testing be enabled for our test token without real
   funds, live purchases, or wallet funding - and if so, what is the
   documented test behavior (responses for success, failure,
   duplicate reference)?
5. Please confirm the duplicate-reference recovery path: given
   `409 duplicate_reference`, is requery via `GET /data/status/?ref=`
   the documented way to establish the original purchase's outcome?

Public contact found on https://meledata.ng: mmtechglobe@gmail.com.
Send only with owner approval.

Opt-in live verification tests: `tests/test_meledata_sandbox_live.py`.
`MELEDATA_LIVE_TESTS=1` (with `MELEDATA_TEST_MODE=1` and a `mele_test_...`
token in `MELEDATA_API_KEY`) enables the READ-ONLY checks: wallet mode
fail-closed gate, catalog integrity, and unowned-reference requery.
The single purchase-attempt test additionally requires
`MELEDATA_PURCHASE_TESTS=1`, so no live verification run ever calls a
purchase endpoint by accident.

## Deliberately NOT done

- No VTpass or MELE DATA entry added to the fulfillment registry: they
  are not routable by purchases in any mode. WiseSub remains the sole
  fulfillment provider, exactly as before.
- No webhook capability claimed for MELE DATA (the provider documents
  none); VTpass webhooks are noted for a future live integration.
- No production database change, no migration, no production
  deployment. Production remains on master (unchanged by this branch).
- No live (production) credentials used anywhere; all live traffic
  targeted sandbox/test endpoints only.

---

# GN Data (gndata.com.ng) readiness review — 2026-10-18

Developer API access is NOT yet approved for our account (requires a
support request per the provider's own Getting Started steps), so no
authenticated live checks exist. All adapter tests are mocked against
the published documentation.

Live evidence gathered WITHOUT credentials (read-only):
- The docs Base URL box prints "http://localhost:8002/api/v1" (docs
  defect; that host is unreachable). An unauthenticated GET to
  https://api.gndata.com.ng/api/v1/wallet/balance returns HTTP 401
  {"detail":"Not authenticated. Provide a valid Bearer token in the
  Authorization header."} — confirming the live host, the /api/v1
  prefix, and the Bearer scheme. The adapter pins HTTPS and rejects
  any non-https GN_DATA_BASE_URL override.

Documentation findings (https://api.gndata.com.ng/api-docs):
- No sandbox/test mode is documented anywhere; only a live API.
- Idempotency-Key header (UUID) is REQUIRED on POST; 409 means
  "duplicate in progress; wait for completion or use a new key" — but
  no endpoint is documented to learn the original outcome.
- NO transaction-status or requery endpoint is documented. Final
  outcomes rely on "transaction.updated" webhook events registered in
  the developer dashboard. Until a verified webhook receiver exists,
  every uncertain purchase (409/504/timeout/unknown) stays pending
  for admin review — the adapter correctly refuses to guess.
- Refund rules are undocumented -> auto_refunds_on_failure=False.
- Webhook payload authentication/signature is undocumented.

Prepared support inquiry for support@gndata.com.ng (NOT sent; contains
no keys or account details):
1. Is a sandbox or test mode available for Developer API purchases,
   or can purchases be tested safely without real funds?
2. Please confirm the official API base URL (the documentation page
   prints http://localhost:8002/api/v1 in its Base URL box).
3. For an HTTP 409 "duplicate Idempotency-Key" response, what is the
   documented way to learn the original transaction's final outcome?
4. Is a transaction-status or requery endpoint available, or are
   "transaction.updated" webhooks the only reconciliation path? Which
   status values can those events carry (pending/failure/success)?
5. How are webhook payloads authenticated (signature/secret), and
   what is the documented behaviour for failed purchases — are
   refunds automatic?
