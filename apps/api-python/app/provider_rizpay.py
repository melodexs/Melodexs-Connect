"""RizPay adapter (developers.rizpay.app).

PREPARED, NOT OPERATIONAL: requires a developer account, an API key
(RIZPAY_API_KEY) and the documented scopes (view_products, purchase_data,
read_transactions). Everything below follows the provider's published
integration guide; sandbox purchases do not deliver real services, so
nothing here has been exercised against the live service yet.

Documented surface (2026-10-17):
- Sandbox base: https://my.rizpay.app/api/partners/sandbox/v1
- Auth: Authorization: Bearer <key>
- Catalogue: GET /products/dataplans (paginated; bundle-family label is
  authoritative and may be null -> then ineligible for equivalence)
- Purchase: POST /purchases {product_id, phone_number, network,
  external_reference}; DUPLICATE_REFERENCE proves usage, not fulfillment
- Status: GET /purchases/:id; data.attributes.status; only "successful"
  is a completed purchase; a purchase may stay pending after acceptance
- Money is decimal; catalogue cost lives in price.amount
"""
from decimal import Decimal, InvalidOperation

import httpx

from .config import settings
from .provider_base import (BalanceResult, CatalogPackage, ProviderAdapter,
                             PurchaseOutcome, PurchaseResult, StatusResult)

NETWORK_VALUES = {"MTN": "MTN", "Airtel": "AIRTEL", "Glo": "GLO", "9mobile": "9MOBILE"}


def _decimal(value) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


class RizPayAdapter(ProviderAdapter):
    slug = "rizpay"
    display_name = "RizPay"
    # RizPay documents failed and reversed outcomes handled per the
    # returned transaction; refunds are not documented as automatic on
    # every failure, so failures stay conservative (uncertain).
    auto_refunds_on_failure = False
    failure_status_is_final = False
    # Retired alternative: excluded from routing, fallback and the admin
    # selection UI (2026-10 provider cleanup); the adapter stays for
    # compatibility tests and historical reconciliation.
    selection_excluded = True
    capabilities = ("catalog", "data", "status")

    def is_configured(self) -> bool:
        return bool(settings.rizpay_api_key)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {settings.rizpay_api_key}", "Accept": "application/json"}

    def _base(self) -> str:
        return (settings.rizpay_base_url or "https://my.rizpay.app/api/partners/sandbox/v1").rstrip("/")

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
                    family = attributes.get("bundle_family")
                    packages.append(CatalogPackage(
                        code=product_id, name=str(attributes.get("name") or product_id),
                        network=str(attributes.get("network") or "").strip().title(),
                        data_size=attributes.get("data_size"),
                        validity=attributes.get("validity"),
                        plan_type=family if isinstance(family, str) and family.strip() else None,
                        cost=cost))
                total_pages = body.get("meta", {}).get("total_pages") or 1
                if page >= int(total_pages):
                    break
                page += 1
        return packages

    async def submit_data_purchase(self, *, network: str, package_code: str, phone: str, reference: str) -> PurchaseResult:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.post(f"{self._base()}/purchases", headers=self._headers(), json={
                    "product_id": int(package_code), "phone_number": phone,
                    "network": NETWORK_VALUES[network], "external_reference": reference})
            body = response.json()
        except Exception:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message="RizPay response was not received")
        if response.status_code >= 500:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message=f"RizPay returned HTTP {response.status_code}")
        if response.status_code == 409 or str(body.get("code") or "") == "DUPLICATE_REFERENCE":
            # A duplicate reference proves the reference was used, NOT that
            # the purchase was fulfilled; must be re-read via status.
            return PurchaseResult(PurchaseOutcome.UNCERTAIN,
                                  message="RizPay reported a duplicate reference; outcome requires reconciliation", raw=body)
        if response.status_code >= 400:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message=f"RizPay returned HTTP {response.status_code} without a confirmed final outcome")
        purchase = body.get("data") or {}
        purchase_id = purchase.get("id")
        status = str(((purchase.get("attributes") or {}).get("status")) or "")
        if purchase_id is None:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message="RizPay response did not include a purchase id")
        # An accepted request can still be pending; only "successful" is
        # a completed purchase per the provider's guide.
        if status == "successful":
            return PurchaseResult(PurchaseOutcome.SUCCESSFUL, provider_reference=str(purchase_id), raw=body)
        return PurchaseResult(PurchaseOutcome.PENDING, provider_reference=str(purchase_id), raw=body)

    async def submit_airtime_purchase(self, *, network: str, phone: str, amount: Decimal, reference: str) -> PurchaseResult:
        raise NotImplementedError("RizPay airtime support is not part of this integration yet")

    async def transaction_status(self, reference: str) -> StatusResult:
        # reference here is the RizPay purchase id (persisted at purchase time)
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
        return BalanceResult(supported=False, message="RizPay's data-bundle guide does not document a wallet balance endpoint.")
