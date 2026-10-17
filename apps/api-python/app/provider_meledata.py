"""MELE DATA adapter (https://meledata.ng/developer/docs).

PREPARED, NOT OPERATIONAL: requires an account and a live API key
(MELE_DATA_API_KEY). All request/response handling below follows the
provider's published documentation exactly; nothing here has been
verified against the live service because no credentials exist yet.

Documented surface (2026-10-17):
- Base URL: https://meledata.ng/api/v1/developer
- Auth: X-API-Key: mele_live_... (token identifies the debited wallet)
- GET /wallet/                       -> {success, data:{balance, currency}}
- GET /data/plans                    -> {plans:[{plan_id, plan_code, network,
                                      plan_name, data_size, validity, price}]}
- POST /data/purchase {network, phone_number, plan_id, reference}
  - idempotent on reference (409 duplicate_reference returns the original)
  - success -> {status:true, data:{status:"success", reference, amount,...}}
  - failure -> {status:false, data:{status:"failed",...}} with documented
    AUTOMATIC wallet refund -> maps to FAILED_FINAL
- GET /data/status/?ref=...           -> {success, data:{status:"delivered"|"failed",
                                       amount_charged, ...}}
- POST /airtime/purchase {network, phone_number, amount(min 100), reference}
"""
import re
from decimal import Decimal, InvalidOperation

import httpx

from .config import settings
from .provider_base import (BalanceResult, CatalogPackage, ProviderAdapter,
                             PurchaseOutcome, PurchaseResult, StatusResult)

MELE_BASE_URL = "https://meledata.ng/api/v1/developer"
NETWORK_VALUES = {"MTN": "MTN", "Airtel": "AIRTEL", "Glo": "GLO", "9mobile": "9MOBILE"}


def _decimal(value) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


class MeleDataAdapter(ProviderAdapter):
    slug = "meledata"
    display_name = "MELE DATA"
    # The provider documents automatic wallet refunds on failed purchases.
    auto_refunds_on_failure = True
    failure_status_is_final = True
    capabilities = ("catalog", "data", "airtime", "status", "balance")

    def is_configured(self) -> bool:
        return bool(settings.meledata_api_key)

    def _headers(self) -> dict:
        return {"X-API-Key": settings.meledata_api_key, "Content-Type": "application/json", "Accept": "application/json"}

    async def fetch_catalog(self) -> list[CatalogPackage]:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(f"{MELE_BASE_URL}/data/plans", headers=self._headers())
            response.raise_for_status()
            body = response.json()
        plans = body.get("plans")
        if not isinstance(plans, list):
            raise ValueError("MELE DATA returned an invalid plan catalog")
        packages: list[CatalogPackage] = []
        for item in plans:
            if not isinstance(item, dict):
                raise ValueError("MELE DATA returned a malformed plan")
            code = str(item.get("plan_code") or "").strip()
            if not code:
                raise ValueError("MELE DATA plan without a stable plan_code")
            cost = _decimal(item.get("price"))
            if cost is None:
                raise ValueError(f"MELE DATA plan {code} has an invalid price")
            packages.append(CatalogPackage(
                code=code, name=str(item.get("plan_name") or "").strip() or code,
                network=str(item.get("network") or "").strip().title(),
                data_size=item.get("data_size"), validity=item.get("validity"),
                plan_type=_plan_family(str(item.get("plan_code") or "") + " " + str(item.get("plan_name") or "")),
                cost=cost))
        return packages

    async def submit_data_purchase(self, *, network: str, package_code: str, phone: str, reference: str) -> PurchaseResult:
        # plan_id is the purchase key; the routing layer resolves the
        # provider plan_id from the stored provider_package_code mapping
        # before calling. package_code carries the MELE plan_id here.
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.post(f"{MELE_BASE_URL}/data/purchase", headers=self._headers(), json={
                    "network": NETWORK_VALUES[network], "phone_number": phone,
                    "plan_id": int(package_code), "reference": reference})
            body = response.json()
        except Exception:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message="MELE DATA response was not received")
        if response.status_code == 409:
            # duplicate_reference: the original request exists; the final
            # outcome is NOT proven by this response.
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message="MELE DATA reported a duplicate reference; outcome requires reconciliation", raw=body)
        if response.status_code >= 500:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message=f"MELE DATA returned HTTP {response.status_code}")
        status = str(((body.get("data") or {}).get("status")) or "")
        if body.get("status") is True and status == "success":
            return PurchaseResult(PurchaseOutcome.SUCCESSFUL, provider_reference=reference,
                                  message=str(body.get("message") or ""), raw=body)
        if body.get("status") is False and status == "failed":
            # Documented: wallet is automatically refunded on failure.
            return PurchaseResult(PurchaseOutcome.FAILED_FINAL,
                                  message=str(body.get("message") or "MELE DATA reported a failed, auto-refunded purchase"), raw=body)
        return PurchaseResult(PurchaseOutcome.UNCERTAIN, message=f"MELE DATA returned HTTP {response.status_code} without a recognized final outcome", raw=body)

    async def submit_airtime_purchase(self, *, network: str, phone: str, amount: Decimal, reference: str) -> PurchaseResult:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.post(f"{MELE_BASE_URL}/airtime/purchase", headers=self._headers(), json={
                    "network": NETWORK_VALUES[network], "phone_number": phone,
                    "amount": float(amount), "reference": reference})
            body = response.json()
        except Exception:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message="MELE DATA response was not received")
        if response.status_code >= 500 or response.status_code == 409:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message=f"MELE DATA returned HTTP {response.status_code}")
        data = body.get("data") or {}
        if body.get("status") is True and str(data.get("status")) == "success":
            return PurchaseResult(PurchaseOutcome.SUCCESSFUL, provider_reference=reference, raw=body)
        return PurchaseResult(PurchaseOutcome.UNCERTAIN, message=f"MELE DATA returned HTTP {response.status_code} without a recognized final outcome", raw=body)

    async def transaction_status(self, reference: str) -> StatusResult:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.get(f"{MELE_BASE_URL}/data/status/",
                                            params={"ref": reference}, headers=self._headers())
            body = response.json()
        except Exception:
            return StatusResult(recognized=False, message="MELE DATA status lookup failed")
        if response.status_code >= 400 or body.get("success") is not True:
            return StatusResult(recognized=False, message=f"MELE DATA returned HTTP {response.status_code}")
        status = str(((body.get("data") or {}).get("status")) or "").strip().lower()
        if status in {"delivered", "successful"}:
            return StatusResult(recognized=True, status="successful")
        if status == "failed":
            return StatusResult(recognized=True, status="failed")
        if status in {"pending", "processing"}:
            return StatusResult(recognized=True, status="pending")
        return StatusResult(recognized=False, message="MELE DATA returned an unrecognized status")

    async def account_balance(self) -> BalanceResult:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.get(f"{MELE_BASE_URL}/wallet/", headers=self._headers())
            body = response.json()
        except Exception as exc:
            return BalanceResult(supported=True, message=f"MELE DATA balance check failed: {type(exc).__name__}")
        if response.status_code >= 400 or body.get("success") is not True:
            return BalanceResult(supported=True, message=f"MELE DATA returned HTTP {response.status_code}")
        data = body.get("data") or {}
        balance = _decimal(data.get("balance"))
        if balance is None:
            return BalanceResult(supported=True, message="MELE DATA returned an unreadable balance")
        return BalanceResult(supported=True, balance=balance,
                             currency=str(data.get("currency") or "NGN"), message="ok")


def _plan_family(text: str) -> str | None:
    """Extract the provider's product family from plan codes/names.

    MELE DATA encodes the family in plan_code (e.g. MTN_1GB_SME). Only
    families the provider itself names are recognized; anything else is
    None, which makes the package ineligible for automatic equivalence.
    """
    lowered = text.lower()
    for family in ("sme", "corporate", "gifting", "cg"):
        if re.search(rf"(^|[^a-z]){family}([^a-z]|$)", lowered):
            return {"cg": "corporate"}.get(family, family)
    return None
