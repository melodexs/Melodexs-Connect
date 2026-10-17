"""WiseSub adapter: wraps the existing, verified WiseSub integration.

The purchase and reconciliation paths in app/main.py continue to call
providers.wise_purchase / wise_status through their long-standing
bindings (tests and the production flow depend on them). This adapter
exposes the same operations through the common ProviderAdapter contract
for the registry, admin tooling and future multi-provider routing, and
its response mapping mirrors main.py's semantics exactly:

- transport exception            -> UNCERTAIN
- HTTP >= 500                    -> UNCERTAIN
- HTTP >= 400 or success != true -> UNCERTAIN (never auto-failed; WiseSub
                                     documents no automatic refunds)
- success == true, with reference -> SUCCESSFUL
- success == true, no reference  -> PENDING
"""
from decimal import Decimal

from .config import settings, validate_wisesub_configuration, wisesub_base_url
from .providers import wise_headers, wise_purchase
from .provider_base import (BalanceResult, CatalogPackage, ProviderAdapter,
                            PurchaseOutcome, PurchaseResult, StatusResult)
import httpx

NETWORK_PROVIDER_CODES = {"MTN": "mtn", "Airtel": "airtel", "Glo": "glo", "9mobile": "9mobile"}


class WiseSubAdapter(ProviderAdapter):
    slug = "wisesub"
    display_name = "WiseSub"
    auto_refunds_on_failure = False
    # WiseSub "failed" statuses only refund after the documented
    # confirmation gate (WISESUB_FAILURE_STATUS_CONFIRMED).
    failure_status_is_final = False
    capabilities = ("catalog", "data", "airtime", "status")

    def is_configured(self) -> bool:
        return bool(settings.wisesub_api_key and settings.wisesub_api_secret)

    async def fetch_catalog(self) -> list[CatalogPackage]:
        # Reuse the proven normalization from plan_sync (same parsing,
        # duplicate-code policy) instead of a second implementation.
        from .plan_sync import NETWORK_NAMES, normalize_package
        packages: list[CatalogPackage] = []
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            for provider_code, network in NETWORK_NAMES.items():
                response = await client.get(
                    f"{wisesub_base_url()}/packages",
                    params={"service_type": "data", "provider_code": provider_code},
                    headers=wise_headers(), follow_redirects=False)
                response.raise_for_status()
                result = response.json()
                raw = (result.get("data") or {}).get("packages") if result.get("success") is True else None
                if not isinstance(raw, list):
                    raise ValueError(f"WiseSub returned an invalid package list for {network}")
                for item in raw:
                    normalized = normalize_package(item)
                    packages.append(CatalogPackage(
                        code=normalized["code"], name=normalized["name"],
                        network=network, data_size=normalized.get("data_size"),
                        validity=normalized.get("validity"), plan_type=None,
                        cost=Decimal(str(normalized["cost"]))))
        return packages

    @staticmethod
    def _purchase(payload: dict, response=None, exc: Exception | None = None) -> PurchaseResult:
        del payload  # payload included in raw responses where available
        if exc is not None:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message="WiseSub response was not received")
        if response.status_code >= 500:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message=f"WiseSub returned HTTP {response.status_code}")
        try:
            body = response.json()
        except Exception:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, message="WiseSub returned an unreadable response")
        if response.status_code >= 400 or body.get("success") is not True:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN,
                                  message=f"WiseSub returned HTTP {response.status_code} without a confirmed final outcome",
                                  raw=body)
        reference = (body.get("data") or {}).get("reference")
        if not reference:
            return PurchaseResult(PurchaseOutcome.PENDING, message="WiseSub response did not include a reference", raw=body)
        return PurchaseResult(PurchaseOutcome.SUCCESSFUL, provider_reference=str(reference), raw=body)

    async def submit_data_purchase(self, *, network: str, package_code: str, phone: str, reference: str) -> PurchaseResult:
        validate_wisesub_configuration(settings)
        payload = {"service_type": "data", "reference": reference,
                   "provider_code": NETWORK_PROVIDER_CODES[network],
                   "package_code": package_code, "recipient": phone}
        try:
            return self._purchase(payload, response=await wise_purchase(payload))
        except Exception as exc:
            return self._purchase(payload, exc=exc)

    async def submit_airtime_purchase(self, *, network: str, phone: str, amount: Decimal, reference: str) -> PurchaseResult:
        validate_wisesub_configuration(settings)
        payload = {"service_type": "airtime", "reference": reference,
                   "provider_code": NETWORK_PROVIDER_CODES[network],
                   "recipient": phone, "amount": float(amount)}
        try:
            return self._purchase(payload, response=await wise_purchase(payload))
        except Exception as exc:
            return self._purchase(payload, exc=exc)

    async def transaction_status(self, reference: str) -> StatusResult:
        from .providers import wise_status
        try:
            response = await wise_status(reference)
            payload = response.json()
        except Exception:
            return StatusResult(recognized=False, message="WiseSub status lookup failed")
        if response.status_code >= 400 or payload.get("success") is not True:
            return StatusResult(recognized=False, message=f"WiseSub returned HTTP {response.status_code}")
        status = str(((payload.get("data") or {}).get("status") or "")).strip().lower()
        if status in {"successful", "failed", "pending"}:
            return StatusResult(recognized=True, status=status)
        return StatusResult(recognized=False, message="Provider response was not a recognized final status")

    async def account_balance(self) -> BalanceResult:
        # WiseSub's partner API documents no wallet balance endpoint.
        return BalanceResult(supported=False, message="WiseSub does not document a balance endpoint.")
