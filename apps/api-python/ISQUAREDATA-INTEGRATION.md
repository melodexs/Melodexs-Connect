# ISQUAREDATA Integration (disabled by default)

Status: **adapter implemented, mocked-tested, DISABLED and unroutable in
production until validation and explicit owner approval.**

This document records the verified API contract, the provider-cleanup
architecture change that accompanies the adapter, and everything that
must still be obtained from ISQUAREDATA before production activation.

## 1. Official documentation sources (verified 2026-10-21)

- Public site + plan/price list: https://isquaredata.com and
  https://isquaredata.com/developer (Service IDs, Plan IDs, "API Price")
- Official API reference (Postman):
  https://documenter.getpostman.com/view/11041569/2s8ZDeUea3
- Support: support@Isquaredata.com, +234 904 543 9441 (WhatsApp),
  office at No. 37 Oladogba Street, Ikosi Ketu, Lagos.

## 2. Verified contract

Base URL: `https://isquaredata.com/api` (HTTPS only; the adapter follows
no redirects and applies connect/read timeouts).

Authentication: HTTP Basic Auth, **verified live 2026-10-21**: the username
is the account's **phone number** and the password is the **dashboard
password** (the published `test:test` pair is rejected with HTTP 403).
Confirmed via read-only `GET /api/balance/`, `GET /api/data/services/`,
`GET /api/data/plans/` and `GET /api/transactions/` (all HTTP 200).
Secret values live only in deployment env vars (`ISQUAREDATA_USERNAME`,
`ISQUAREDATA_PASSWORD`), never in this repository. The webhook signature
`user_key` is documented as the profile USER ID; the dashboard profile
shows a UUID, which is the presumed key (unverified until a signed
webhook arrives).

**Live catalog findings (2026-10-21):** `GET /api/data/services/` returns
8 active services / 156 plans; `GLO NORMAL DATA` and `GLO SME` are
disabled provider-side ("unstable" per the dashboard notice), so the Glo
cost advantages in the comparison below are **not currently purchasable**.
`GET /api/data/plans/` returns all 209 plans including disabled ones; the
adapter uses the active `/data/services/` snapshot. Plan records carry
extra undocumented fields (`value_size` GB quantity, per-plan
`commission`, `custom_gateway`) usable as catalog metadata.

| Purpose | Method & path | Notes |
|---|---|---|
| Data catalog (per service) | `GET /data/services/` | `[{id, name, plans: [{id, custom_name, name, enduser_amount, reseller_amount, api_amount, is_active, network}], is_active}]` |
| Data catalog (flat) | `GET /data/plans/` | Same plan fields flat |
| Buy data | `POST /data/buy/` | `{plan: <plan id>, phone_number, reference, disable_validation, webhook_url}`. **No response body documented**; docs state the TRUE status arrives via the webhook. |
| Transaction list | `GET /transactions/` | Paginated; statuses seen: `success`, `failed`, `pending`, `credited` |
| Transaction detail | `GET /transactions/{reference}/` | Requery by our own reference |
| Wallet balance | `GET /balance/` | `{wallet_balance, referral_balance}` |
| Webhook | POST to our `webhook_url` | Header `x-isquare-signature` = HMAC-SHA512(raw body, USER ID from the dashboard profile) |

Pricing: the plan objects carry **three documented price tiers** -
`enduser_amount`, `reseller_amount`, `api_amount`. The adapter uses
`api_amount` as the supplier cost (API-specific reseller cost, confirmed
by the public developer page labelling the same values "API Price").

Networks/families: plan rows carry a `network` integer that is NOT a
stable enum (the official examples show networks 1/2/3 across MTN SME,
MTN GIFTING and AIRTEL services). The adapter therefore derives the
network and product family from the **service name** (verified strings
such as "MTN SME DATA", "AIRTEL DATA"), skips and reports services whose
names do not map to a known network, and never guesses.

## 3. Safety posture (by design)

- `auto_refunds_on_failure = False`, `failure_status_is_final = False`:
  ISQUAREDATA documents NO automatic-refund guarantee, so a failed
  purchase can never be finalized from the purchase response alone.
- A purchase response is **never** mapped to SUCCESSFUL: the API
  documents no response body and says the true status arrives by
  webhook - accepted requests are PENDING and reconciled via
  `GET /transactions/{reference}/` (and later the signed webhook).
- Timeouts, HTTP 4xx/5xx and malformed bodies are UNCERTAIN: the wallet
  debit stays held until reconciliation; no automatic retry.
- Duplicate-reference/idempotency semantics are NOT documented: purchases
  are never resubmitted against a potentially-successful submission.
- Credentials are only read from settings; error messages never include
  the Authorization header or credentials (regression-tested).
- The provider registers disabled and unconfigured by default;
  `resolve_fulfillment_provider()` refuses it until it is configured,
  enabled AND multi-provider routing is deliberately switched on.

## 4. Catalog cost comparison (read-only, 2026-10-21)

Matched products only (same network + allowance + validity + family).
iSquare column = published "API Price"; WiseSub column = current
production supplier cost (post-discount-restoration sync, 2026-10-20).

| Product | iSquare API cost | WiseSub cost | Delta |
|---|---:|---:|---:|
| MTN 110MB / 1 day | 98.00 | 98.20 | -0.2% |
| MTN 2GB / 2 days | 727.50 | 736.50 | -1.2% |
| MTN 3.2GB / 2 days | 970.00 | 982.00 | -1.2% |
| MTN 6GB / 7 days | 2,425.00 | 2,455.00 | -1.2% |
| MTN 10GB+10mins / 30 days | 4,365.00 | 4,419.00 | -1.2% |
| Airtel 1.5GB Binge / 2 days | 580.00 | 587.80 | -1.3% |
| Airtel 5GB Binge / 2 days | 1,448.00 | 1,469.40 | -1.5% |
| Airtel 1.5GB Weekly | 965.00 | 979.60 | -1.5% |
| Airtel 3GB Monthly | 1,930.00 | 1,959.20 | -1.5% |
| Airtel 8GB Monthly | 2,895.00 | 2,938.80 | -1.5% |
| Glo 1.1GB+1.5GB night / 30d | 935.00 | 976.00 | -4.2% |
| Glo 3.15GB+3GB night / 30d | 1,870.00 | 1,952.00 | -4.2% |
| Glo 4.25GB+3GB night / 30d | 2,337.50 | 2,440.00 | -4.2% |
| Glo 310GB / 60 days | 46,750.00 | 48,800.00 | -4.2% |
| Glo 475GB / 90 days | 70,125.00 | 73,200.00 | -4.2% |
| 9mobile T2 4.5GB / 30d | 1,960.00 | 1,952.00 | +0.4% |
| 9mobile T2 5.2GB / 30d | 2,445.00 | 2,440.00 | +0.2% |
| 9mobile T2 11.4GB / 30d | 4,880.00 | 4,880.00 | 0.0% |
| 9mobile 650MB / 3 days | 490.00 | 488.00 | +0.4% |

Findings: iSquareData is consistently cheaper on MTN (~1.2%), Airtel
(~1.5%) and Glo (~4.2%, including the 475GB/90d mega), and identical on
9mobile T2 (same upstream likely). ISQUAREDATA also sells families
WiseSub does not offer at all - MTN Datashare/SME/Corporate/Coupon,
Airtel Special/Awoof/Corporate, Glo CG/SME and 9mobile Corporate - which
map to the affordability gaps identified in the WiseSub product-value
audit. These comparisons used the public price list because no API
credentials exist yet; they must be re-verified against the live
`GET /data/plans/` response before any routing decision.

The established `ceil(cost * 1.02)` markup is NOT applied to ISQUAREDATA
anywhere yet; no prices were written to production.

## 5. Environment variables required (names only, never values)

- `ISQUAREDATA_USERNAME` - Basic-auth username from the dashboard
- `ISQUAREDATA_PASSWORD` - Basic-auth password
- `ISQUAREDATA_WEBHOOK_URL` - optional; per-purchase webhook target,
  leave unset until a signed webhook receiver is built and validated

WiseSub's credentials, routing and 2% markup are untouched.

## 6. Provider cleanup (this change)

The intended architecture is now explicit in the registry:

| Provider | Status | Where |
|---|---|---|
| WiseSub | ACTIVE production provider (sole routable) | `provider_wisesub.py`, registry primary |
| ISQUAREDATA | Next provider: registered, disabled, unconfigured | `provider_isquaredata.py` |
| MELE DATA | Retired alternative: adapter kept, **selection-excluded** | `provider_meledata.py` |
| RizPay | Retired alternative: adapter kept, **selection-excluded** | `provider_rizpay.py` |
| VTpass | Sandbox-only validation tooling; never was a registry adapter | `vtpass_sandbox.py` |
| GN Data | Experimental, unmerged branch (PR #29); absent from master and production | `feat/gndata-adapter` |

"Selection-excluded" means: absent from the admin provider-selection
list, rejected by the enable endpoint (HTTP 409), never eligible for
fulfillment or fallback, and refused by `resolve_fulfillment_provider()`
even if its database row were enabled manually. The adapters, tests,
database rows and credentials remain untouched for compatibility and
historical reconciliation; no secrets, migrations, transaction history or
WiseSub behavior changed.

## 7. Outstanding requirements before production activation

1. ISQUAREDATA account + real API credentials (dashboard Basic-auth
   username/password; the documented `test:test` is rejected live).
2. Support confirmation of duplicate-reference/idempotency semantics for
   `/data/buy/` (a reference is accepted, but no documented dedupe).
3. A sandbox or test mode that cannot debit real funds (the docs'
   "Testing" endpoint is empty; none documented).
4. Refund behavior for failed data purchases (not documented).
5. Live re-verification of the catalog costs (public price list vs the
   authenticated `api_amount` values).
6. A signed webhook receiver (`x-isquare-signature` HMAC-SHA512 with the
   dashboard USER ID) plus reconciliation wiring, built and validated.
7. Owner approval: enabling the provider row AND turning on multi-provider
   routing remain separate, explicit decisions.

## 8. Tests

`tests/test_isquaredata_adapter.py` (12 tests): catalog normalization
(service-name networks, `api_amount` cost, inactive-plan exclusion,
unmapped-service reporting, malformed envelope), purchase semantics
(2xx -> PENDING never SUCCESSFUL, timeout/4xx/5xx -> UNCERTAIN, payload
shape, credential redaction), status normalization (success/failed/pending
+ unrecognized values + non-200), balance, airtime NotImplementedError,
conservative defaults. `tests/test_provider_platform.py` updated:
excluded providers absent from the selection list and un-enableable,
ISQUAREDATA present-but-disabled, routing status reports exclusions,
WiseSub protections unchanged. Suite: 254 passed, 20 skipped on a fresh
scratch SQLite database.
