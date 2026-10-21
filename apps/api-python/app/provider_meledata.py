"""MELE DATA adapter (https://meledata.ng/developer/docs).

Verified contract (2026-10-18, official developer documentation):
- ONE base URL serves live and test traffic: https://meledata.ng/api/v1/developer.
  There is no separate sandbox host. The API key itself selects the mode:
  mele_test_... keys simulate purchases without debiting the real wallet.
- Auth: X-API-Key: <token> (Bearer also accepted by the provider; this
  adapter uses the documented X-API-Key form).
- GET  /wallet/ -> {"success": true, "data": {"balance", "display",
  "currency": "NGN", "livemode": bool, "mode": "live"|"test"}}.
  The mode/livemode fields are authoritative and this adapter enforces
  them whenever MELEDATA_TEST_MODE is set (fail closed on live mode or
  inconsistent indicators).
- GET  /data/plans -> {"status": true, "message", "data": {"plans": [{plan_id
  (int), plan_code, network (MTN|GLO|AIRTEL|9MOBILE), plan_name, data_size,
  validity, price}]}} (verified live 2026-10-18: the envelope nests plans
  under data, and the boolean field is "status", not "success")
- POST /data/purchase {network, phone_number (11 digits), plan_id (int),
  reference (string, max 80 chars)}. Idempotent on reference.
  - success -> {"success": true, "message", "data": {"status": "success", ...}}
  - carrier rejection -> {"status": false, "data": {"status": "failed", ...}}
    WITH a DOCUMENTED automatic wallet refund.
  - 409 duplicate_reference when a reference is reused outside the
    documented idempotent-retry path; the outcome is NOT proven by the
    409 - requery GET /data/status/?ref=... is the documented recovery.
- GET  /data/status?ref=... -> {"success": true, "data": {"status":
  "delivered"|"failed", "amount_charged", ...}}. Only "delivered" and
  "failed" are documented; anything else is unrecognized (uncertain).
  Unknown/foreign references return {"status": false, "message":
  "No purchase with that reference is owned by your client."}.
- LIVE URL CORRECTION (2026-10-18): /wallet/ and /data/status/ 308-redirect
  to their no-trailing-slash forms; this adapter calls the final URLs
  directly because it follows no redirects.
- LIVE LIMITATION (2026-10-18): test tokens (mele_test_...) read the
  wallet (mode "test", balance 1,000,000) and the catalog, but every
  test purchase currently returns HTTP 400 "Insufficient wallet
  balance." against that balance. MELE test purchases are therefore NOT
  verified end-to-end; the purchase paths are covered by mocked
  contract tests only, and enabling live MELE routing requires the
  provider to confirm test-purchase behavior first.
- POST /airtime/purchase {network, phone_number, amount (min 100), reference}
- Errors: 401 invalid_token, 403 account_inactive, 404 not_found,
  400 invalid_request, 400 insufficient_balance, 409 duplicate_reference,
  429 rate_limited, 500 server_error.

NOT supported by the provider (documented absence - never invent them):
webhooks/callbacks, transaction history listing, airtime status requery.

Safety posture:
- auto_refunds_on_failure=True and failure_status_is_final=True because
  the provider DOCUMENTS automatic wallet refunds on carrier rejection;
  the platform therefore never issues an additional independent refund
  on top of the provider's.
- Purchases that time out or return malformed/unknown bodies are
  UNCERTAIN: they stay pending and are resolved only through the
  documented status requery (or the gated admin reconciliation flow).
"""
from decimal import Decimal, InvalidOperation

import httpx

from .config import settings
from .provider_base import (BalanceResult, CatalogPackage, ProviderAdapter,
                             PurchaseOutcome, PurchaseResult, StatusResult)

MELE_BASE_URL = "https://meledata.ng/api/v1/developer"
MAX_REFERENCE_LENGTH = 80
NETWORK_VALUES = {"MTN": "MTN", "Airtel": "AIRTEL", "Glo": "GLO", "9mobile": "9MOBILE"}
# Provider network values (uppercase) -> platform display form.
NETWORK_DISPLAY = {"MTN": "MTN", "GLO": "Glo", "AIRTEL": "Airtel", "9MOBILE": "9mobile"}


def _decimal(value) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _valid_reference(reference: str) -> bool:
    text = str(reference or "").strip()
    return bool(text) and len(text) <= MAX_REFERENCE_LENGTH


def _plan_family(code: str, name: str = "") -> str | None:
    """Extract the provider's own product family from plan_code/name.

    MELE DATA encodes the family in plan_code (e.g. MTN_1GB_SME). Only
    families the provider itself names are recognized; anything else is
    None, which keeps the package ineligible for automatic equivalence
    matching (see app/package_matching.py).
    """
    import re
    lowered = f"{code} {name}".lower()
    for family in ("sme", "corporate", "gifting", "cg"):
        if re.search(rf"(^|[^a-z]){family}([^a-z]|$)", lowered):
            return {"cg": "corporate"}.get(family, family)
    return None


def _normalize_mode(data: dict) -> tuple[str | None, bool | None]:
    mode = data.get("mode")
    livemode = data.get("livemode")
    return (str(mode).strip().lower() if isinstance(mode, str) else None,
            bool(livemode) if isinstance(livemode, bool) else None)


class MeleDataAdapter(ProviderAdapter):
    slug = "meledata"
    display_name = "MELE DATA"
    # The provider documents automatic wallet refunds on failed purchases.
    auto_refunds_on_failure = True
    failure_status_is_final = True
    capabilities = ("catalog", "data", "airtime", "status", "balance")
    # Retired alternative: excluded from routing, fallback and the admin
    # selection UI (2026-10 provider cleanup); the adapter stays for
    # compatibility tests and historical reconciliation.
    selection_excluded = True

    def is_configured(self) -> bool:
        return bool(self.meledata_api_key)

    @property
    def meledata_api_key(self) -> str | None:
        return getattr(settings, "meledata_api_key", None)

    def _base(self) -> str:
        return (getattr(settings, "meledata_base_url", None) or MELE_BASE_URL).rstrip("/")

    def _headers(self) -> dict:
        return {"X-API-Key": self.meledata_api_key or "",
                "Content-Type": "application/json", "Accept": "application/json"}

    # ------------------------------------------------------ mode safety

    async def _test_mode_gate(self) -> str | None:
        """Fail closed when MELEDATA_TEST_MODE is set but the provider
        reports a live, inconsistent or unreadable wallet mode.

        Returns None when purchases may proceed; otherwise a sanitized
        refusal message. An unreachable wallet is a REFUSAL, never a
        pass-through: an unverifiable mode must not become a purchase.
        """
        if not settings.meledata_test_mode:
            return None
        balance = await self.account_balance()
        if not balance.supported or balance.balance is None:
            return balance.message or "MELE DATA wallet check failed; refusing to purchase"
        if balance.mode != "test" or balance.livemode is not False:
            return ("MELE DATA test mode is configured but the provider reported "
                    f"mode={balance.mode!r} livemode={balance.livemode!r}; "
                    "refusing sandbox purchases")
        return None

    # ---------------------------------------------------------- catalog

    async def fetch_catalog(self) -> list[CatalogPackage]:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(f"{self._base()}/data/plans", headers=self._headers())
            response.raise_for_status()
            body = response.json()
        # Verified live: {"status": true, "data": {"plans": [...]}}.
        if body.get("status") is not True or not isinstance(body.get("data"), dict):
            raise ValueError("MELE DATA returned an invalid catalog envelope")
        plans = body["data"].get("plans")
        if not isinstance(plans, list):
            raise ValueError("MELE DATA returned an invalid plan catalog")
        packages: list[CatalogPackage] = []
        seen_ids: set[int] = set()
        for item in plans:
            if not isinstance(item, dict):
                raise ValueError("MELE DATA returned a malformed plan")
            plan_id = item.get("plan_id")
            # Documented type: plan_id is an int purchase key.
            if not isinstance(plan_id, int) or isinstance(plan_id, bool):
                raise ValueError("MELE DATA plan without an integer plan_id")
            if plan_id in seen_ids:
                raise ValueError(f"MELE DATA returned a duplicate plan_id: {plan_id}")
            seen_ids.add(plan_id)
            code = str(item.get("plan_code") or "").strip()
            if not code:
                raise ValueError(f"MELE DATA plan {plan_id} has no stable plan_code")
            cost = _decimal(item.get("price"))
            if cost is None:
                raise ValueError(f"MELE DATA plan {code} has an invalid price")
            name = str(item.get("plan_name") or "").strip() or code
            provider_network = str(item.get("network") or "").strip().upper()
            display_network = NETWORK_DISPLAY.get(provider_network)
            if display_network is None:
                # Unknown networks are never silently mapped to a known one.
                raise ValueError(f"MELE DATA plan {code} has an unrecognized network: "
                                 f"{provider_network!r}")
            packages.append(CatalogPackage(
                code=str(plan_id), name=name,
                network=display_network,
                data_size=item.get("data_size"), validity=item.get("validity"),
                plan_type=_plan_family(code, name), cost=cost))
        return packages

    # --------------------------------------------------------- purchase

    async def submit_data_purchase(self, *, network: str, package_code: str,
                                    phone: str, reference: str) -> PurchaseResult:
        if not _valid_reference(reference):
            return PurchaseResult(PurchaseOutcome.UNCERTAIN,
                                  message="Purchase reference is not a valid MELE DATA reference")
        if settings.meledata_test_mode:
            refusal = await self._test_mode_gate()
            if refusal is not None:
                return PurchaseResult(PurchaseOutcome.UNCERTAIN, message=refusal)
        try:
            plan_id = int(str(package_code))
        except (TypeError, ValueError):
            return PurchaseResult(PurchaseOutcome.UNCERTAIN,
                                  message="Package code does not resolve to a MELE DATA plan_id")
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.post(f"{self._base()}/data/purchase",
                                             headers=self._headers(),
                                             json={"network": NETWORK_VALUES[network],
                                                   "phone_number": phone,
                                                   "plan_id": plan_id,
                                                   "reference": reference})
            body = response.json()
        except Exception:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN,
                                  message="MELE DATA response was not received; requery required")
        return self._map_purchase(response.status_code, body, reference)

    def _map_purchase(self, status_code: int, body: dict, reference: str) -> PurchaseResult:
        if status_code >= 500:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=reference,
                                  message=f"MELE DATA returned HTTP {status_code}")
        if status_code == 409:
            # duplicate_reference proves the reference was used, NOT that
            # the purchase succeeded; the documented recovery is requery.
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=reference,
                                  message="MELE DATA reported a duplicate reference; outcome "
                                          "requires reconciliation via the status requery",
                                  raw=body)
        if status_code in {401, 403}:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=reference,
                                  message="MELE DATA rejected the request without a purchase outcome")
        data = body.get("data") if isinstance(body, dict) else None
        status = str((data or {}).get("status") or "").strip().lower()
        if body.get("status") is True and status == "success":
            return PurchaseResult(PurchaseOutcome.SUCCESSFUL, provider_reference=reference,
                                  message=str(body.get("message") or "MELE DATA purchase accepted"),
                                  raw=body)
        if body.get("status") is False and status == "failed":
            # Documented automatic wallet refund on carrier rejection.
            # The platform records the final failure WITHOUT issuing an
            # independent duplicate refund.
            return PurchaseResult(PurchaseOutcome.FAILED_FINAL, provider_reference=reference,
                                  message=str(body.get("message")
                                              or "MELE DATA reported a failed, auto-refunded purchase"),
                                  raw=body)
        return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=reference,
                              message=f"MELE DATA returned HTTP {status_code} without a recognized "
                                      "final outcome",
                              raw=body)

    async def submit_airtime_purchase(self, *, network: str, phone: str,
                                      amount: Decimal, reference: str) -> PurchaseResult:
        if not _valid_reference(reference):
            return PurchaseResult(PurchaseOutcome.UNCERTAIN,
                                  message="Purchase reference is not a valid MELE DATA reference")
        if settings.meledata_test_mode:
            refusal = await self._test_mode_gate()
            if refusal is not None:
                return PurchaseResult(PurchaseOutcome.UNCERTAIN, message=refusal)
        amount_decimal = _decimal(amount)
        if amount_decimal is None or amount_decimal < 100:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN,
                                  message="Airtime amount is below MELE DATA's documented minimum of 100")
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.post(f"{self._base()}/airtime/purchase",
                                             headers=self._headers(),
                                             json={"network": NETWORK_VALUES[network],
                                                   "phone_number": phone,
                                                   "amount": float(amount_decimal),
                                                   "reference": reference})
            body = response.json()
        except Exception:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN,
                                  message="MELE DATA response was not received; outcome requires reconciliation")
        if response.status_code >= 500:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=reference,
                                  message=f"MELE DATA returned HTTP {response.status_code}")
        if response.status_code == 409:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=reference,
                                  message="MELE DATA reported a duplicate reference; outcome "
                                          "requires reconciliation")
        data = body.get("data") or {}
        if body.get("status") is True and str(data.get("status")) == "success":
            return PurchaseResult(PurchaseOutcome.SUCCESSFUL, provider_reference=reference,
                                  message=str(body.get("message") or ""), raw=body)
        if body.get("status") is False and str(data.get("status")) == "failed":
            # Same documented auto-refund semantics as data purchases.
            return PurchaseResult(PurchaseOutcome.FAILED_FINAL, provider_reference=reference,
                                  message=str(body.get("message") or "MELE DATA reported a failed, auto-refunded purchase"),
                                  raw=body)
        return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=reference,
                              message=f"MELE DATA returned HTTP {response.status_code} without a recognized final outcome")

    # ----------------------------------------------------- status requery

    async def transaction_status(self, reference: str) -> StatusResult:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.get(f"{self._base()}/data/status",
                                            params={"ref": reference}, headers=self._headers())
            body = response.json()
        except Exception:
            return StatusResult(recognized=False, message="MELE DATA status lookup failed")
        if response.status_code >= 400 or body.get("success") is not True:
            return StatusResult(recognized=False,
                                message=f"MELE DATA returned HTTP {response.status_code}")
        status = str(((body.get("data") or {}).get("status")) or "").strip().lower()
        # Only the two DOCUMENTED requery statuses are recognized. An
        # unknown value is never treated as success or failure.
        if status == "delivered":
            return StatusResult(recognized=True, status="successful")
        if status == "failed":
            return StatusResult(recognized=True, status="failed")
        return StatusResult(recognized=False,
                            message="MELE DATA returned a status not covered by its documentation")

    # ---------------------------------------------------------- balance

    async def account_balance(self) -> BalanceResult:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.get(f"{self._base()}/wallet", headers=self._headers())
            body = response.json()
        except Exception as exc:
            return BalanceResult(supported=True,
                                 message=f"MELE DATA balance check failed: {type(exc).__name__}")
        if response.status_code >= 400 or body.get("success") is not True:
            return BalanceResult(supported=True,
                                 message=f"MELE DATA returned HTTP {response.status_code}")
        data = body.get("data") or {}
        balance = _decimal(data.get("balance"))
        if balance is None:
            return BalanceResult(supported=True, message="MELE DATA returned an unreadable balance")
        mode, livemode = _normalize_mode(data)
        if settings.meledata_test_mode and (mode != "test" or livemode is not False):
            return BalanceResult(supported=False, balance=balance,
                                 currency=str(data.get("currency") or "NGN"),
                                 mode=mode, livemode=livemode,
                                 message="MELE DATA test mode is configured but the provider "
                                         f"reported mode={mode!r} livemode={livemode!r}; "
                                         "refusing to continue")
        return BalanceResult(supported=True, balance=balance,
                             currency=str(data.get("currency") or "NGN"),
                             mode=mode, livemode=livemode, message="ok")
