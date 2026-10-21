"""ISQUAREDATA adapter (https://isquaredata.com/api, official Postman docs:
https://documenter.getpostman.com/view/11041569/2s8ZDeUea3).

Verified contract (2026-10-21, official documentation only):
- ONE base URL: https://isquaredata.com/api (HTTPS only; this adapter
  follows no redirects).
- Auth: HTTP Basic Auth. The published examples use placeholder
  credentials (test:test) which the live API REJECTS with 403 (verified
  2026-10-21); real credentials must be obtained from the ISQUAREDATA
  dashboard / support. Env: ISQUAREDATA_USERNAME / ISQUAREDATA_PASSWORD.
- GET /data/services/ -> [{"id", "name" (e.g. "MTN SME DATA",
  "MTN GIFTING DATA", "AIRTEL DATA"), "plans": [{id, custom_name, name,
  enduser_amount, reseller_amount, api_amount, is_active, network}],
  "is_active"}]. The public developer page (isquaredata.com/developer)
  renders the same catalog with Service IDs and Plan IDs.
  The per-plan "network" integer is NOT a stable network enum (the
  service-list examples show network 1/2/3 across MTN SME, MTN GIFTING
  and AIRTEL services), so network + product family are derived from the
  SERVICE NAME (verified strings); plans under services whose name does
  not map to a known network are skipped and reported.
  api_amount is the documented API-specific cost (the price list has
  three tiers: enduser_amount / reseller_amount / api_amount).
- GET /data/plans/ -> flat plan list (same fields).
- POST /data/buy/ {"plan": <plan id int>, "phone_number", "reference",
  "disable_validation": false, "webhook_url": ...}. The documentation
  explicitly states: rely on the webhook_url to get the TRUE status of
  the transaction, and documents NO response body for data purchases.
  This adapter therefore NEVER maps a purchase response to SUCCESSFUL:
  any accepted 2xx response is PENDING, to be reconciled via the
  documented transaction status endpoint (and, once built and
  validated, the signed webhook).
- GET /transactions/<reference>/ -> {"service", "amount", "date",
  "reference", "status": "success"|"failed"|"pending", "old_balance",
  "new_balance", "comment", "remark", "phone"}. Status values verified
  from the official examples: success, failed, pending (the transaction
  history also shows "credited" for wallet funding, which this adapter
  treats as unrecognized for purchases). Behavior for unknown
  references is NOT documented; non-200 responses surface as
  unrecognized (uncertain), never as success or failure.
- GET /balance/ -> {"wallet_balance": <number>, "referral_balance"}.
- Webhook (documented, NOT yet implemented here): POST to the
  webhook_url given per purchase, body like the transaction detail, with
  header x-isquare-signature = HMAC-SHA512(raw_body, user_key) where
  user_key is the USER ID on the dashboard profile. A signed webhook
  receiver is a prerequisite for production activation; until it is
  built and validated, reconciliation uses the status endpoint only.
- Error responses (documented for the buy family): HTTP 400 with a
  field-mapped body such as {"plan_id": ["Insufficient balance to
  perform transaction! Please fund your wallet"]}. Refund behavior on
  failed data purchases is NOT documented anywhere.

NOT verified / blocked on ISQUAREDATA support:
- production Basic-auth credential names (dashboard) and their account
  linkage;
- duplicate-reference/idempotency semantics for /data/buy/ (a reference
  is accepted and echoed, but no documented duplicate protection);
- whether a sandbox/test mode exists that cannot debit real funds (the
  docs' "Testing" endpoint is empty);
- refund behavior for failed or reversed purchases.

Safety posture (deliberately conservative):
- auto_refunds_on_failure=False and failure_status_is_final=False: no
  documented refunds, so purchase failures are UNCERTAIN and final
  states are only reached through the gated reconciliation flow.
- Timeouts, HTTP errors and malformed bodies are UNCERTAIN; the wallet
  debit stays held until the status requery (or admin) resolves it.
- Purchases are never retried against a potentially-successful
  submission: without documented duplicate protection, a retry with the
  same reference is assumed to be a NEW purchase.
"""
import re
from base64 import b64encode
from decimal import Decimal, InvalidOperation

import httpx

from .config import settings
from .provider_base import (BalanceResult, CatalogPackage, ProviderAdapter,
                             PurchaseOutcome, PurchaseResult, StatusResult)

ISQUARE_BASE_URL = "https://isquaredata.com/api"
ISQUARE_TIMEOUT = 30.0
MAX_REFERENCE_LENGTH = 100

# Verified service-name keywords -> platform display networks.
NETWORK_KEYWORDS = (
    ("9MOBILE", "9mobile"),
    ("ETISALAT", "9mobile"),
    # 9mobile's reseller family is named "T2 DATA" with no carrier in
    # the service name. Verified against the live catalog (2026-10-21):
    # its plans match WiseSub's 9mobile T2 family one-to-one (83MB
    # DAILY, 650MB 3-DAYS, 2GB MONTHLY ... at near-identical costs).
    ("T2", "9mobile"),
    ("AIRTEL", "Airtel"),
    ("GLO", "Glo"),
    ("MTN", "MTN"),
)

# Verified product-family keywords in service names (provider's own
# naming only; anything else stays None, which keeps packages
# ineligible for automatic equivalence matching).
FAMILY_KEYWORDS = ("SME", "GIFTING", "CORPORATE", "CG", "COUPON", "DATASHARE")


def _network_from_service_name(service_name: str) -> str | None:
    upper = str(service_name or "").upper()
    for keyword, display in NETWORK_KEYWORDS:
        if keyword in upper:
            return display
    return None


def _family_from_service_name(service_name: str) -> str | None:
    upper = str(service_name or "").upper()
    for family in FAMILY_KEYWORDS:
        if re.search(rf"(^|[^A-Z]){family}([^A-Z]|$)", upper):
            return {"CG": "corporate"}.get(family, family.lower())
    return None


def _decimal(value) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _valid_reference(reference: str) -> bool:
    text = str(reference or "").strip()
    return bool(text) and len(text) <= MAX_REFERENCE_LENGTH


def _parse_size(name: str) -> str | None:
    text = str(name or "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(MB|GB|TB)\b", text, re.I)
    if match:
        return f"{match.group(1)}{match.group(2).upper()}"
    # ISQUAREDATA names some plans with a bare megabyte count and the
    # validity (e.g. "750 2weeks"); only the documented bare-number form
    # is treated as MB, never a bare GB-scale guess.
    bare = re.match(r"^(\d{3,4})\s+(?:\d+\s*-?\s*days?\b|\d+\s*-?\s*weeks?\b)", text, re.I)
    if bare:
        return f"{bare.group(1)}MB"
    return None


def _parse_validity(name: str) -> str | None:
    text = str(name or "").lower()
    days = re.search(r"(\d+)\s*-?\s*days?\b", text)
    if days:
        return f"{days.group(1)} days"
    if re.search(r"2\s*-?\s*weeks?", text):
        return "14 days"
    if "weekly" in text:
        return "7 days"
    if "monthly" in text or re.search(r"\bmonth\b", text):
        return "30 days"
    if "daily" in text:
        return "1 day"
    return None


class IsquareDataAdapter(ProviderAdapter):
    slug = "isquaredata"
    display_name = "ISQUAREDATA"
    # No documented automatic refunds; every failure is reconciled, never
    # assumed refunded.
    auto_refunds_on_failure = False
    failure_status_is_final = False
    capabilities = ("catalog", "data", "status", "balance")

    def is_configured(self) -> bool:
        return bool(self._auth_header_value())

    def _auth_header_value(self) -> str | None:
        username = (settings.isquaredata_username or "").strip()
        password = (settings.isquaredata_password or "")
        if not username or not password:
            return None
        token = b64encode(f"{username}:{password}".encode()).decode()
        return f"Basic {token}"

    def _headers(self) -> dict:
        auth = self._auth_header_value()
        if not auth:
            raise RuntimeError("ISQUAREDATA credentials are not configured")
        return {"Authorization": auth, "Accept": "application/json",
                "Content-Type": "application/json"}

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise RuntimeError("ISQUAREDATA credentials are not configured")

    async def fetch_catalog(self) -> list[CatalogPackage]:
        """Fetch the verified service list; network and family come from
        the service name, cost from the documented api_amount field."""
        self._require_configured()
        async with httpx.AsyncClient(timeout=ISQUARE_TIMEOUT,
                                     follow_redirects=False) as client:
            response = await client.get(f"{ISQUARE_BASE_URL}/data/services/",
                                       headers=self._headers())
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, list):
            raise ValueError("ISQUAREDATA services response is not a list")
        packages: list[CatalogPackage] = []
        skipped: list[str] = []
        for service in body:
            if not isinstance(service, dict) or not service.get("is_active", True):
                continue
            service_name = str(service.get("name") or "")
            network = _network_from_service_name(service_name)
            family = _family_from_service_name(service_name)
            plans = service.get("plans")
            if network is None or not isinstance(plans, list):
                skipped.append(service_name or "<unnamed service>")
                continue
            for plan in plans:
                if not isinstance(plan, dict) or not plan.get("is_active", True):
                    continue
                cost = _decimal(plan.get("api_amount"))
                plan_id = plan.get("id")
                name = str(plan.get("name") or "").strip()
                if cost is None or not isinstance(plan_id, int) or not name:
                    continue  # malformed plan row: never guess an identifier
                packages.append(CatalogPackage(
                    code=str(plan_id),
                    name=name,
                    network=network,
                    data_size=_parse_size(name),
                    validity=_parse_validity(name),
                    plan_type=family,
                    cost=cost,
                ))
        if skipped:
            # Read-only catalog fetch: unknown services are skipped and
            # reported, never guessed.
            raise ValueError(
                "ISQUAREDATA services with unmapped networks were skipped: "
                + ", ".join(sorted(set(skipped))))
        return packages

    async def submit_data_purchase(self, *, network: str, package_code: str,
                                   phone: str, reference: str) -> PurchaseResult:
        self._require_configured()
        if not _valid_reference(reference):
            return PurchaseResult(outcome=PurchaseOutcome.UNCERTAIN,
                                  message="Invalid reference for ISQUAREDATA purchase")
        try:
            plan_id = int(str(package_code))
        except (TypeError, ValueError):
            return PurchaseResult(outcome=PurchaseOutcome.UNCERTAIN,
                                  message="ISQUAREDATA package code must be a plan id")
        payload = {
            "plan": plan_id,
            "phone_number": str(phone).strip(),
            "reference": str(reference).strip(),
            "disable_validation": False,
        }
        webhook_url = (settings.isquaredata_webhook_url or "").strip()
        if webhook_url:
            payload["webhook_url"] = webhook_url
        try:
            async with httpx.AsyncClient(timeout=ISQUARE_TIMEOUT,
                                         follow_redirects=False) as client:
                response = await client.post(f"{ISQUARE_BASE_URL}/data/buy/",
                                            headers=self._headers(), json=payload)
        except httpx.HTTPError as exc:
            return PurchaseResult(outcome=PurchaseOutcome.UNCERTAIN,
                                  message=f"ISQUAREDATA request failed: {type(exc).__name__}")
        if response.status_code >= 500 or response.status_code in (401, 403, 404, 429):
            return PurchaseResult(outcome=PurchaseOutcome.UNCERTAIN,
                                  message=f"ISQUAREDATA returned HTTP {response.status_code}")
        if response.status_code >= 400:
            # Documented shape (e.g. insufficient balance) is a field-mapped
            # error; refunds are NOT documented, so this stays UNCERTAIN and
            # is resolved through the status requery / gated reconciliation.
            return PurchaseResult(outcome=PurchaseOutcome.UNCERTAIN,
                                  message=f"ISQUAREDATA rejected the purchase (HTTP {response.status_code})")
        # The API documents NO response body for data purchases and states
        # the TRUE status arrives via webhook/requery: never SUCCESSFUL here.
        return PurchaseResult(outcome=PurchaseOutcome.PENDING,
                              message="ISQUAREDATA accepted the request; outcome pending reconciliation")

    async def submit_airtime_purchase(self, *, network: str,
                                      phone: str, amount: Decimal,
                                      reference: str) -> PurchaseResult:
        # The airtime endpoint exists in the documentation but is out of
        # scope until the data path is validated end to end.
        raise NotImplementedError("ISQUAREDATA airtime purchases are not implemented")

    async def transaction_status(self, reference: str) -> StatusResult:
        self._require_configured()
        text = str(reference or "").strip()
        if not _valid_reference(text):
            return StatusResult(recognized=False,
                                message="Invalid reference for ISQUAREDATA status lookup")
        try:
            async with httpx.AsyncClient(timeout=ISQUARE_TIMEOUT,
                                         follow_redirects=False) as client:
                response = await client.get(
                    f"{ISQUARE_BASE_URL}/transactions/{text}/",
                    headers=self._headers())
        except httpx.HTTPError as exc:
            return StatusResult(recognized=False,
                                message=f"ISQUAREDATA status request failed: {type(exc).__name__}")
        if response.status_code != 200:
            return StatusResult(recognized=False,
                                message=f"ISQUAREDATA status returned HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            return StatusResult(recognized=False,
                                message="ISQUAREDATA status response is not valid JSON")
        if not isinstance(body, dict) or body.get("reference") != text:
            return StatusResult(recognized=False,
                                message="ISQUAREDATA status response did not echo the reference")
        status = str(body.get("status") or "").strip().lower()
        if status == "success":
            return StatusResult(recognized=True, status="successful")
        if status == "failed":
            return StatusResult(recognized=True, status="failed")
        if status == "pending":
            return StatusResult(recognized=True, status="pending")
        return StatusResult(recognized=False,
                            message=f"ISQUAREDATA reported unrecognized status {status!r}")

    async def account_balance(self) -> BalanceResult:
        self._require_configured()
        try:
            async with httpx.AsyncClient(timeout=ISQUARE_TIMEOUT,
                                         follow_redirects=False) as client:
                response = await client.get(f"{ISQUARE_BASE_URL}/balance/",
                                           headers=self._headers())
        except httpx.HTTPError as exc:
            return BalanceResult(supported=True,
                                 message=f"ISQUAREDATA balance request failed: {type(exc).__name__}")
        if response.status_code != 200:
            return BalanceResult(supported=True,
                                 message=f"ISQUAREDATA balance returned HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            return BalanceResult(supported=True,
                                 message="ISQUAREDATA balance response is not valid JSON")
        balance = _decimal(body.get("wallet_balance")) if isinstance(body, dict) else None
        if balance is None:
            return BalanceResult(supported=True,
                                 message="ISQUAREDATA balance response missing wallet_balance")
        return BalanceResult(supported=True, balance=balance, currency="NGN")
