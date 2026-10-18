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
(`tests/test_meledata_adapter.py`, 18 tests). Enabling live MELE routing
must wait until the provider confirms test-purchase behavior (support
contact recommended before any live integration).

Opt-in live verification tests: `tests/test_meledata_sandbox_live.py`
(4 tests, all passing 2026-10-18): wallet mode fail-closed gate, catalog
integrity, refused-purchase-without-debit safety, and unowned-reference
requery. Enable with `MELEDATA_LIVE_TESTS=1`, `MELEDATA_TEST_MODE=1` and a
`mele_test_...` token in `MELEDATA_API_KEY`.

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
