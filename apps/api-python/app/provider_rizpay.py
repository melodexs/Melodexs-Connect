"""RizPay adapter (https://developers.rizpay.app).

PREPARED, NOT OPERATIONAL: requires a business account, API settings
activation, and a key (RIZPAY_API_KEY) with the documented scopes
(view_products, purchase_data, read_transactions, read_balance).
A sandbox key (sk_test_...) works against the sandbox base URL and
performs NO real purchases, deliveries, or wallet debits, so the
integration can be verified end-to-end without funding anything.

Verified against the provider's current documentation (2026-10-17):
- Environments: production https://my.rizpay.app/api/partners/v1,
  sandbox https://my.rizpay.app/api/partners/sandbox/v1 (sk_test_ keys
  must be used with the sandbox URL; ENVIRONMENT_MISMATCH otherwise).
- Auth: "Authorization: Bearer sk_test_..."; scoped keys.
- Catalogue: GET /products/dataplans?network=&bundle_type= (paginated)
  -> {status:{code,message}, data:[{id:"prd_2270", attributes:{
     display_name, network, bundle_size, duration, bundle_type, price:{
     amount (your cost, decimal string), currency, basis:"fixed"}}}],
     pagination:{page, per_page, total_pages, total_count}}
  bundle_type is the plan family and may be null -> then ineligible
  for automatic equivalence matching.
- Purchase: POST /purchases {product_id ("prd_..." string), phone_number,
  network, external_reference}; amount NOT needed for data plans.
  -> 201 {status:{code:201}, data:{id:"txn_...", attributes:{status}}}
  external_reference MUST match /^\\d{10}[a-zA-Z0-9]{6}$/ (10-digit unix
  timestamp + 6 alphanumeric); a re-used reference returns
  DUPLICATE_REFERENCE (an error.code, not a special HTTP status).
- Errors: {status:{code:<http>}, error:{code, message, details}};
  machine-readable code lives at error.code. Notable 400 codes:
  DUPLICATE_REFERENCE, INSUFFICIENT_BALANCE, PRODUCT_UNAVAILABLE,
  PURCHASE_FAILED, PROVIDER_ERROR; 429 RATE_LIMIT_EXCEEDED
  (sandbox 60 req/min); 500 server errors.
- Status: GET /purchases/:id -> data.attributes.status in
  {pending, processing, successful, failed, reversed}; only
  "successful" is a completed purchase. "reversed" is a post-debit
  reversal (refunds not documented as automatic).
- Balance: GET /account/balance (read_balance scope) ->
  {data:{balance:"50000.00", currency:"NGN"}}; the sandbox returns a
  mock balance (100000.00).
- Sandbox behaviour (documented): purchases create mock transactions
  whose outcome follows the TEST RECIPIENT: 08011111111 immediately
  successful; 08022222222 pending->successful; 08033333333
  pending->failed; 08044444444 INSUFFICIENT_BALANCE; 08066666666
  reversed; any other number PURCHASE_FAILED. POST /purchases/:id/query
  completes any pending sandbox transaction as successful.
"""
import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx

from .config import settings
from .provider_base import (BalanceResult, CatalogPackage, ProviderAdapter,
                             PurchaseOutcome, PurchaseResult, StatusResult)

NETWORK_VALUES = {"MTN": "MTN", "Airtel": "AIRTEL", "Glo": "GLO", "9mobile": "9MOBILE"}
_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_EXTERNAL_REFERENCE_RE_OK = None  # format enforced by external_reference_for()


def _decimal(value) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def external_reference_for(reference: str) -> str:
    """Map a MELODEXS reference to RizPay's required reference format.

    The provider requires /^\\d{10}[a-zA-Z0-9]{6}$/: a 10-digit unix
    timestamp plus 6 alphanumeric characters. Our references begin with
    a 12-digit Lagos timestamp (YYYYMMDDHHMM), which converts directly;
    the 6-character suffix is derived deterministically from the full
    reference, so RETRIES OF THE SAME ORDER SEND THE SAME
    external_reference and hit DUPLICATE_REFERENCE instead of
    double-purchasing.
    """
    digest = hashlib.sha256(reference.encode()).digest()
    suffix = "".join(_BASE62[b % 62] for b in digest[:6])
    try:
        stamp = datetime.strptime(str(reference)[:12], "%Y%m%d%H%M")
        ts = int(stamp.replace(tzinfo=ZoneInfo("Africa/Lagos")).timestamp())
    except ValueError:
        # Deterministic fallback keeps the required shape without
        # depending on wall-clock time (retries must map identically).
        ts = int.from_bytes(digest[6:11], "big") % 10**10
    return f"{ts:010d}{suffix}"


class RizPayAdapter(ProviderAdapter):
    slug = "rizpay"
    display_name = "RizPay"
    # Refunds/reversals are not documented as automatic on every
    # failure, so failures stay conservative (uncertain).
    auto_refunds_on_failure = False
    failure_status_is_final = False
    capabilities = ("catalog", "data", "status", "balance")

    def is_configured(self) -> bool:
        return bool(settings.rizpay_api_key)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {settings.rizpay_api_key}",
                "Accept": "application/json"}

    def _base(self) -> str:
        return (settings.rizpay_base_url or "https://my.rizpay.app/api/partners/sandbox/v1").rstrip("/")

    @staticmethod
    def _error_code(body: dict) -> str:
        error = body.get("error")
        return str((error or {}).get("code") or "") if isinstance(error, dict) else ""

    async def fetch_catalog(self) -> list[CatalogPackage]:
        packages: list[CatalogPackage] = []
        page = 1
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            while True:
                response = await client.get(f"{self._base()}/products/dataplans",
                                            params={"page": page}, headers=self._headers())
                response.raise_for_status()
                body = response.json()
                items = body.get("data") or []
                if not isinstance(items, list):
                    raise ValueError("RizPay returned an invalid catalogue page")
                for item in items:
                    if not isinstance(item, dict):
                        raise ValueError("RizPay returned a malformed catalogue entry")
                    product_id = str(item.get("id") or "").strip()
                    if not product_id:
                        raise ValueError("RizPay catalogue entry without a product id")
                    attributes = item.get("attributes") or {}
                    price = ((attributes.get("price") or {}).get("amount"))
                    cost = _decimal(price)
                    if cost is None:
                        raise ValueError(f"RizPay product {product_id} has an invalid price")
                    family = attributes.get("bundle_type")
                    packages.append(CatalogPackage(
                        code=product_id,
                        name=str(attributes.get("display_name") or product_id),
                        network=str(attributes.get("network") or "").strip().title(),
                        data_size=attributes.get("bundle_size"),
                        validity=attributes.get("duration"),
                        plan_type=family if isinstance(family, str) and family.strip() else None,
                        cost=cost))
                pagination = body.get("pagination") or {}
                total_pages = pagination.get("total_pages") or 1
                if page >= int(total_pages):
                    break
                page += 1
        return packages

    async def submit_data_purchase(self, *, network: str, package_code: str, phone: str, reference: str) -> PurchaseResult:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.post(f"{self._base()}/purchases", headers=self._headers(), json={
                    # Product ids are strings like "prd_2270".
                    "product_id": str(package_code),
                    "phone_number": phone,
                    "network": NETWORK_VALUES[network],
                    # Provider-required format; deterministic per order.
                    "external_reference": external_reference_for(reference)})
            body = response.json()
        except Exception:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message="RizPay response was not received")
        if response.status_code >= 500:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message=f"RizPay returned HTTP {response.status_code}", raw=body)
        if self._error_code(body) == "DUPLICATE_REFERENCE":
            # A duplicate reference proves the reference was used, NOT
            # that the purchase was fulfilled; it must be re-read via
            # the purchase status endpoint.
            return PurchaseResult(PurchaseOutcome.UNCERTAIN,
                                  message="RizPay reported a duplicate reference; outcome requires reconciliation", raw=body)
        if response.status_code >= 400:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN,
                                  message=f"RizPay returned HTTP {response.status_code} ({self._error_code(body) or 'unknown error'}) without a confirmed final outcome",
                                  raw=body)
        purchase = body.get("data") or {}
        purchase_id = purchase.get("id")
        status = str(((purchase.get("attributes") or {}).get("status")) or "")
        if purchase_id is None:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message="RizPay response did not include a purchase id", raw=body)
        # An accepted request can still be pending; only "successful"
        # is a completed purchase per the provider's docs.
        if status == "successful":
            return PurchaseResult(PurchaseOutcome.SUCCESSFUL, provider_reference=str(purchase_id), raw=body)
        return PurchaseResult(PurchaseOutcome.PENDING, provider_reference=str(purchase_id), raw=body)

    async def submit_airtime_purchase(self, *, network: str, phone: str, amount: Decimal, reference: str) -> PurchaseResult:
        raise NotImplementedError("RizPay airtime support is not part of this integration yet")

    async def transaction_status(self, reference: str) -> StatusResult:
        # reference here is the RizPay transaction id (persisted at purchase time)
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.get(f"{self._base()}/purchases/{reference}", headers=self._headers())
            body = response.json()
        except Exception:
            return StatusResult(recognized=False, message="RizPay status lookup failed")
        if response.status_code >= 400:
            return StatusResult(recognized=False, message=f"RizPay returned HTTP {response.status_code}")
        status = str((((body.get("data") or {}).get("attributes")) or {}).get("status") or "").strip().lower()
        if status == "successful":
            return StatusResult(recognized=True, status="successful")
        if status in {"failed", "reversed"}:
            return StatusResult(recognized=True, status="failed")
        if status in {"pending", "processing", "initiated"}:
            return StatusResult(recognized=True, status="pending")
        return StatusResult(recognized=False, message="RizPay returned an unrecognized status")

    async def account_balance(self) -> BalanceResult:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.get(f"{self._base()}/account/balance", headers=self._headers())
            body = response.json()
        except Exception as exc:
            return BalanceResult(supported=True, message=f"RizPay balance check failed: {type(exc).__name__}")
        if response.status_code >= 400:
            return BalanceResult(supported=True, message=f"RizPay returned HTTP {response.status_code}")
        data = body.get("data") or {}
        balance = _decimal(data.get("balance"))
        if balance is None:
            return BalanceResult(supported=True, message="RizPay returned an unreadable balance")
        return BalanceResult(supported=True, balance=balance,
                             currency=str(data.get("currency") or "NGN"), message="ok")
