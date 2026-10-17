"""GN Data adapter (https://api.gndata.com.ng/ - "GN DATA Developer Portal v1.0").

PREPARED, NOT OPERATIONAL: requires a registered account, Developer API
access approved by GN Data support, and a live API key (GN_DATA_API_KEY).
All request/response handling below follows the provider's published
documentation exactly; nothing here has been verified against the live
service because no credentials exist yet.

Documented surface (checked 2026-10-17):
- Auth: "Authorization: Bearer <API_KEY>" (auto-detected developer key;
  no transaction PIN for developer API requests)
- POST requests additionally REQUIRE an "Idempotency-Key" header: a
  unique UUID per purchase request; HTTP 409 means that key is already
  in progress (duplicate protection)
- Base URL note: the documentation page prints
  "http://localhost:8002/api/v1" in its Base URL box (a docs defect);
  the provider's own sample asset URLs use https://api.gndata.com.ng.
  The public portal domain is used here and MUST be re-verified against
  the live service before any purchase (see GN_DATA_BASE_URL override).
- GET /api/v1/wallet/balance -> {balance, currency, user_id, email,
  account_numbers:[...funding accounts]}
- GET /api/v1/data/services?include_plans=true -> networks with nested
  plans (plans may be null; then GET /api/v1/data/plans/{network_id})
- GET /api/v1/data/plans/{network_id} -> [{id, name, network_id, price,
  duration, validity, type, total_data, available}]; "Prices returned
  reflect your developer API user rate"
- POST /api/v1/data/purchase {phone, network_id, plan_id}
  - 200 -> {request_id, status:"success", amount, transaction_id, message}
  - 400 -> invalid parameters or insufficient wallet balance (no debit)
  - 409 -> duplicate Idempotency-Key in progress
  - 504 -> upstream timeout; "transaction is marked pending for
    automated sync or admin review" -> UNCERTAIN
- Transaction status: NO requery endpoint is documented. Delivery of
  final outcomes relies on "transaction.updated" webhook events
  registered in the developer dashboard. Until a webhook receiver is
  built and verified, this adapter reports status lookups as
  unsupported and the platform must treat unresolved purchases as
  UNCERTAIN (never success, never failure, no blind fallback).
- Refund behavior: NOT documented -> auto_refunds_on_failure=False.
"""
import re
import uuid
from decimal import Decimal, InvalidOperation

import httpx

from .config import settings
from .provider_base import (BalanceResult, CatalogPackage, ProviderAdapter,
                             PurchaseOutcome, PurchaseResult, StatusResult)

GN_DEFAULT_BASE_URL = "https://api.gndata.com.ng/api/v1"
# Deterministic UUID derivation: retries of the same MELODEXS reference
# reuse the same Idempotency-Key, so the provider's duplicate protection
# also protects our own retries. Different references always differ.
_IDEMPOTENCY_NAMESPACE = uuid.UUID("a54f6f0a-27f8-4f1f-9d6e-1f9a2b5c7d01")

# The portal labels networks like "MTN Data"; normalize to display form.
_NETWORK_NORMALIZERS = {
    "mtn": "MTN", "airtel": "Airtel", "glo": "Glo", "9mobile": "9mobile",
    "etisalat": "9mobile",
}


def _base_url() -> str:
    return (settings.gndata_base_url or GN_DEFAULT_BASE_URL).rstrip("/")


def _decimal(value) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _network_display(name: str) -> str | None:
    token = (name or "").strip().lower().replace(" data", "").replace(" airtime", "")
    return _NETWORK_NORMALIZERS.get(token)


def _plan_family(value) -> str | None:
    """Pass through the provider's own product family, never a guess.

    GN Data labels families explicitly (SME, Corporate, Gifting,
    Coupon, Social). Unknown or missing labels stay None, which keeps
    the package ineligible for automatic equivalence matching.
    """
    text = str(value or "").strip().lower()
    if not text:
        return None
    if re.search(r"(^|[^a-z])(sme|corporate|gifting|coupon|social)([^a-z]|$)", text):
        return text
    return None


def idempotency_key_for(reference: str) -> str:
    """A stable UUID per MELODEXS purchase reference (documented format)."""
    return str(uuid.uuid5(_IDEMPOTENCY_NAMESPACE, reference))


class GnDataAdapter(ProviderAdapter):
    slug = "gndata"
    display_name = "GN Data"
    # No automatic refund is documented for failed purchases.
    auto_refunds_on_failure = False
    failure_status_is_final = False
    capabilities = ("catalog", "data", "balance")

    def is_configured(self) -> bool:
        return bool(settings.gndata_api_key)

    def _headers(self, *, post: bool = False, reference: str | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {settings.gndata_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if post:
            # Documented as REQUIRED on every purchase request.
            headers["Idempotency-Key"] = idempotency_key_for(reference or "")
        return headers

    async def fetch_catalog(self) -> list[CatalogPackage]:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(f"{_base_url()}/data/services",
                                        params={"include_plans": "true"},
                                        headers=self._headers())
            response.raise_for_status()
            networks = response.json()
        if not isinstance(networks, list):
            raise ValueError("GN Data returned an invalid data network list")
        packages: list[CatalogPackage] = []
        for network in networks:
            if not isinstance(network, dict) or not network.get("available", True):
                continue
            display = _network_display(str(network.get("name") or ""))
            network_id = network.get("id")
            if display is None or network_id is None:
                # Unknown networks are skipped, never guessed into a
                # supported network.
                continue
            plans = network.get("plans")
            if not isinstance(plans, list):
                plans = await self._plans_for_network(network_id)
            for plan in plans:
                package = self._package_from_plan(plan, display, network_id)
                if package is not None:
                    packages.append(package)
        return packages

    async def _plans_for_network(self, network_id) -> list:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(f"{_base_url()}/data/plans/{network_id}",
                                        headers=self._headers())
            response.raise_for_status()
            plans = response.json()
        if not isinstance(plans, list):
            raise ValueError("GN Data returned an invalid plan list")
        return plans

    def _package_from_plan(self, plan, display_network: str, network_id) -> CatalogPackage | None:
        if not isinstance(plan, dict):
            raise ValueError("GN Data returned a malformed plan")
        if plan.get("available") is False:
            return None
        plan_id = plan.get("id")
        if plan_id is None:
            raise ValueError("GN Data plan without a stable id")
        cost = _decimal(plan.get("price"))
        if cost is None:
            raise ValueError(f"GN Data plan {plan_id} has an invalid price")
        return CatalogPackage(
            # Composite internal code: plan ids are documented per network
            # response only, so the purchase key carries both.
            code=f"{network_id}:{plan_id}",
            name=str(plan.get("name") or "").strip() or str(plan_id),
            network=display_network,
            data_size=plan.get("total_data"),
            validity=plan.get("validity"),
            plan_type=_plan_family(plan.get("type")),
            cost=cost)

    async def submit_data_purchase(self, *, network: str, package_code: str, phone: str, reference: str) -> PurchaseResult:
        try:
            network_id, _, plan_id = package_code.partition(":")
            if not network_id or not plan_id:
                return PurchaseResult(PurchaseOutcome.FAILED_FINAL,
                                     message="Invalid GN Data plan mapping; nothing was sent to the provider")
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.post(f"{_base_url()}/data/purchase",
                                             headers=self._headers(post=True, reference=reference),
                                             json={"phone": phone,
                                                   "network_id": int(network_id),
                                                   "plan_id": int(plan_id)})
        except Exception:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message="GN Data response was not received")
        try:
            body = response.json()
        except Exception:
            body = {}
        if response.status_code == 409:
            # Duplicate Idempotency-Key: the original request exists but
            # its outcome is NOT proven by this response.
            return PurchaseResult(PurchaseOutcome.UNCERTAIN,
                                 message="GN Data reported a duplicate idempotency key; outcome requires reconciliation",
                                 raw=body)
        if response.status_code == 400:
            # Documented as invalid parameters or insufficient wallet
            # balance; no debit occurs, so the customer wallet is
            # safely restored.
            return PurchaseResult(PurchaseOutcome.FAILED_FINAL,
                                  message=str(body.get("message") or "GN Data rejected the purchase (no debit occurred)"),
                                  raw=body)
        if response.status_code == 504 or response.status_code >= 500:
            # 504 is documented as "marked pending for automated sync or
            # admin review" -> uncertain, never a final failure.
            return PurchaseResult(PurchaseOutcome.UNCERTAIN,
                                  message=f"GN Data returned HTTP {response.status_code}; purchase is pending review",
                                  raw=body)
        if str(body.get("status") or "") == "success":
            return PurchaseResult(PurchaseOutcome.SUCCESSFUL,
                                  provider_reference=str(body.get("request_id") or "") or reference,
                                  message=str(body.get("message") or ""), raw=body)
        return PurchaseResult(PurchaseOutcome.UNCERTAIN,
                              message=f"GN Data returned HTTP {response.status_code} without a recognized final outcome",
                              raw=body)

    async def submit_airtime_purchase(self, *, network: str, phone: str, amount, reference: str) -> PurchaseResult:
        # GN Data documents an airtime purchase endpoint, but airtime is
        # not part of this integration phase.
        raise NotImplementedError("GN Data airtime support is not part of this integration yet")

    async def transaction_status(self, reference: str) -> StatusResult:
        # No requery endpoint is documented; reconciliation depends on
        # webhook events. Report unsupported so callers keep treating
        # the purchase as uncertain.
        return StatusResult(recognized=False,
                            message="GN Data does not document a transaction status lookup; reconciliation relies on webhook events")

    async def account_balance(self) -> BalanceResult:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.get(f"{_base_url()}/wallet/balance",
                                            headers=self._headers())
            body = response.json()
        except Exception as exc:
            return BalanceResult(supported=True, message=f"GN Data balance check failed: {type(exc).__name__}")
        if response.status_code >= 400:
            return BalanceResult(supported=True, message=f"GN Data returned HTTP {response.status_code}")
        balance = _decimal(body.get("balance"))
        if balance is None:
            return BalanceResult(supported=True, message="GN Data returned an unreadable balance")
        return BalanceResult(supported=True, balance=balance,
                             currency=str(body.get("currency") or "NGN"), message="ok")
