"""VTpass sandbox validation client (https://vtpass.com/documentation/).

Sandbox-only tooling: this module validates the VTpass contract against
the provider's SANDBOX environment. It is deliberately NOT part of the
fulfillment registry (providers are added to the platform only after
sandbox validation and an explicit owner decision). Every network call
runs through assert_sandbox_url(), which fails closed unless the base
URL is the documented sandbox host. Live credentials can never be used
here by accident because the live host is rejected outright.

Verified contract (2026-10-18, official docs + live sandbox probing):
- Sandbox base URL: https://sandbox.vtpass.com/api
- GET requests: api-key + public-key headers
- POST requests: api-key + secret-key headers
- GET  /balance -> {"code": 1, "contents": {"balance": "2000000.00"}}
  (no currency field is returned; the wallet is Naira)
- GET  /service-variations?serviceID=<service> -> response_description
  "000" with content.variations[]: variation_code (string), name,
  variation_amount ("100.00" string), fixedPrice ("Yes"/"No")
- POST /pay {request_id, serviceID, phone, variation_code}:
  the recipient field is "phone" (the docs' billersCode is not accepted
  by the sandbox API; invalid/missing phone yields code 011)
  - delivered: code "000", response_description "TRANSACTION SUCCESSFUL",
    content.transactions.status "delivered"
  - failed:    code "016", content.transactions.status "failed"
  - pending:   code "000", "TRANSACTION PROCESSING", status "pending"
  - duplicate request_id: code "014" "REQUEST ID ALREADY EXIST"
    (VTpass does NOT return the original response; requery is the only
    documented recovery path)
- POST /requery {request_id} -> same envelope; unknown id: code "015"
- request_id (per the documented generation guide): >= 12 chars,
  alphanumeric only, first 12 chars numeric YYYYMMDDHHII (today's date)
- Documented sandbox test phones (mtn-data documentation page):
  08011111111 successful; 201000000000 pending; 500000000000 unexpected
  response; 400000000000 no response (HTTP 200, EMPTY body); 300000000000
  timeout; any other number failed
- Sandbox wallet: successful purchase debited unit price minus a 4%
  commission; failed and pending scenarios did not debit (auto-reversed)
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
import secrets

import httpx

from .provider_base import PurchaseOutcome, PurchaseResult, StatusResult

VTPASS_SANDBOX_BASE_URL = "https://sandbox.vtpass.com/api"
VTPASS_SANDBOX_HOST = "sandbox.vtpass.com"

# Documented sandbox test phones and the outcome they simulate.
TEST_PHONES = {
    "08011111111": "successful",
    "201000000000": "pending",
    "500000000000": "unexpected",
    "400000000000": "no_response",
    "300000000000": "timeout",
}

# Terminal status values observed in content.transactions.status.
_DELIVERED = {"delivered"}
_FAILED = {"failed"}
_PENDING = {"pending", "sent", "requeued"}


class VtpassSandboxError(RuntimeError):
    """Sandbox configuration or contract violation (never carries secrets)."""


def assert_sandbox_url(base_url: str) -> str:
    """Fail closed unless base_url is the approved sandbox host."""
    parsed = urlsplit(str(base_url or ""))
    if parsed.scheme != "https" or parsed.netloc.strip().lower() != VTPASS_SANDBOX_HOST:
        raise VtpassSandboxError(
            "VTpass sandbox tooling refuses to run: the configured base URL is not "
            f"https://{VTPASS_SANDBOX_HOST}. Live endpoints are never used by sandbox validation.")
    return f"https://{VTPASS_SANDBOX_HOST}/api"


def new_request_id() -> str:
    """Generate a request_id per VTpass's documented format."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    return stamp + secrets.token_hex(5)


def request_id_is_wellformed(request_id: str) -> bool:
    """Structural check from the documented generation guide.

    (>= 12 chars, alphanumeric only, first 12 chars numeric). The
    date component is checked against today only when generating.
    """
    text = str(request_id or "")
    return (len(text) >= 12 and text.isalnum() and text[:12].isdigit())


def _decimal(value) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


@dataclass(frozen=True)
class VtpassCatalog:
    """Validated variation list for one service.

    variations excludes any entry whose variation_code appears more than
    once in the provider response: an ambiguous code is never silently
    treated as a distinct purchasable product. duplicate_codes reports
    exactly which codes were ambiguous (verified live 2026-10-18: the
    sandbox catalogs for mtn-data/glo-data/etisalat-data each contain
    duplicated codes, e.g. mtn-xtratalk-300).
    """
    service_id: str
    service_name: str
    variations: list
    duplicate_codes: list


@dataclass(frozen=True)
class VtpassVariation:
    code: str
    name: str
    amount: Decimal
    fixed_price: bool
    data_size: str | None
    validity: str | None


def _parse_variation_name(name: str) -> tuple[str | None, str | None]:
    """Split 'N100 100MB - 24 hrs' into (data_size, validity).

    Returns (None, None) when the name does not contain a recognizable
    size/validity so the package stays ineligible for automatic
    equivalence matching (see app/package_matching.py).
    """
    import re
    size = validity = None
    size_match = re.search(r"(\d+(?:\.\d+)?\s*(?:KB|MB|GB|TB))", name, re.I)
    if size_match:
        size = size_match.group(1)
    # Validity is the segment after the LAST hyphen (verified against
    # live sandbox names: "Airtel Data Bundle - 50 Naira - 25MB  - 1Day").
    rest = re.sub(r"(\d+(?:\.\d+)?\s*(?:KB|MB|GB|TB))", "", name, count=1, flags=re.I)
    if "-" in rest:
        validity = rest.rsplit("-", 1)[-1].strip()
    return size, validity


@dataclass(frozen=True)
class VtpassSandboxClient:
    api_key: str = ""
    public_key: str = ""
    secret_key: str = ""
    base_url: str = VTPASS_SANDBOX_BASE_URL
    timeout: float = 30.0

    @property
    def sandbox_base(self) -> str:
        return assert_sandbox_url(self.base_url)

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.public_key and self.secret_key)

    def _get_headers(self) -> dict:
        if not self.configured:
            raise VtpassSandboxError("VTpass sandbox credentials are not configured")
        return {"api-key": self.api_key, "public-key": self.public_key,
                "Accept": "application/json"}

    def _post_headers(self) -> dict:
        if not self.configured:
            raise VtpassSandboxError("VTpass sandbox credentials are not configured")
        return {"api-key": self.api_key, "secret-key": self.secret_key,
                "Content-Type": "application/json", "Accept": "application/json"}

    # ----------------------------------------------------------- catalog

    async def service_variations(self, service_id: str) -> VtpassCatalog:
        """Fetch and validate one service's variation list.

        Raises VtpassSandboxError on transport errors, auth failures and
        malformed structures (missing fields, invalid amounts). Duplicate
        variation codes are REPORTED (never silently deduped): every entry
        with an ambiguous code is excluded from the returned variations
        and listed in duplicate_codes.
        """
        base = self.sandbox_base
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            response = await client.get(f"{base}/service-variations",
                                         params={"serviceID": service_id},
                                         headers=self._get_headers())
        body = self._json(response, "service-variations")
        if str(body.get("response_description")) != "000":
            raise VtpassSandboxError(
                f"VTpass service-variations({service_id}) returned a non-success response")
        content = body.get("content")
        service_name = str(content.get("ServiceName") or "").strip() \
            if isinstance(content, dict) else ""
        variations = content.get("variations") if isinstance(content, dict) else None
        if not isinstance(variations, list) or not variations:
            raise VtpassSandboxError(
                f"VTpass service-variations({service_id}) returned no variations")
        packages: list[VtpassVariation] = []
        counts: dict[str, int] = {}
        for item in variations:
            if not isinstance(item, dict):
                raise VtpassSandboxError("VTpass returned a malformed variation entry")
            code = str(item.get("variation_code") or "").strip()
            if not code:
                raise VtpassSandboxError("VTpass variation without a variation_code")
            amount = _decimal(item.get("variation_amount"))
            if amount is None:
                raise VtpassSandboxError(f"VTpass variation {code} has an invalid amount")
            name = str(item.get("name") or "").strip()
            if not name:
                raise VtpassSandboxError(f"VTpass variation {code} has no name")
            counts[code] = counts.get(code, 0) + 1
            size, validity = _parse_variation_name(name)
            packages.append(VtpassVariation(
                code=code, name=name, amount=amount,
                fixed_price=str(item.get("fixedPrice") or "").strip().lower() == "yes",
                data_size=size, validity=validity))
        duplicate_codes = sorted(code for code, n in counts.items() if n > 1)
        unambiguous = [v for v in packages if counts[v.code] == 1]
        return VtpassCatalog(service_id=service_id, service_name=service_name,
                            variations=unambiguous, duplicate_codes=duplicate_codes)

    # ---------------------------------------------------------- balance

    async def balance(self) -> Decimal:
        """Read the sandbox wallet balance (mock money, never real)."""
        base = self.sandbox_base
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            response = await client.get(f"{base}/balance", headers=self._get_headers())
        body = self._json(response, "balance")
        # Live sandbox 2026-10-18: {"code": 1, "contents": {"balance": "..."}}
        value = _decimal(((body.get("contents") or {}).get("balance"))
                         if isinstance(body.get("contents"), dict) else None)
        if value is None:
            raise VtpassSandboxError("VTpass balance response did not contain a balance")
        return value

    # --------------------------------------------------------- purchase

    async def purchase(self, *, service_id: str, variation_code: str,
                       phone: str, request_id: str) -> PurchaseResult:
        """Submit a sandbox purchase using a documented test scenario.

        request_id must be well-formed per the documented guide. The
        sandbox host is re-checked fail-closed on every call.
        """
        if not request_id_is_wellformed(request_id):
            raise VtpassSandboxError("request_id does not match the documented VTpass format")
        base = self.sandbox_base
        payload = {"request_id": request_id, "serviceID": service_id,
                   "phone": phone, "variation_code": variation_code}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.post(f"{base}/pay", headers=self._post_headers(), json=payload)
        except httpx.HTTPError:
            # Timeout (documented scenario 300000000000) or transport
            # failure: the request may still have been accepted. The
            # outcome is uncertain; only requery may resolve it.
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=request_id,
                                  message="VTpass response was not received; requery required")
        try:
            body = response.json()
        except ValueError:
            # Documented "no response" scenario (400000000000): HTTP 200
            # with an EMPTY body. Uncertain; requery required.
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=request_id,
                                  message=f"VTpass returned HTTP {response.status_code} without a JSON body")
        return self._map_purchase_response(request_id, response.status_code, body)

    def _map_purchase_response(self, request_id: str, status_code: int, body: dict) -> PurchaseResult:
        code = str(body.get("code") or "")
        transactions = (body.get("content") or {}).get("transactions") \
            if isinstance(body.get("content"), dict) else None
        status = str((transactions or {}).get("status") or "").strip().lower() \
            if isinstance(transactions, dict) else ""
        if code == "000" and status in _DELIVERED:
            return PurchaseResult(PurchaseOutcome.SUCCESSFUL, provider_reference=request_id,
                                  message="VTpass reported the purchase delivered", raw={"code": code, "status": status})
        if code == "000" and status in _PENDING:
            return PurchaseResult(PurchaseOutcome.PENDING, provider_reference=request_id,
                                  message="VTpass reported the purchase processing; requery for the final status",
                                  raw={"code": code, "status": status})
        if code == "016" and status in _FAILED:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=request_id,
                                  message="VTpass reported a failed purchase; VTpass does not document "
                                          "an automatic wallet refund, so the failure must be reconciled "
                                          "before any refund decision",
                                  raw={"code": code, "status": status})
        if code == "014":
            # REQUEST ID ALREADY EXIST: VTpass does not return the original
            # response on a retry. The outcome is uncertain; requery only.
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=request_id,
                                  message="VTpass rejected a duplicate request_id; requery the original request",
                                  raw={"code": code})
        if status_code >= 500:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=request_id,
                                  message=f"VTpass returned HTTP {status_code}")
        if status_code >= 400:
            return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=request_id,
                                  message=f"VTpass returned HTTP {status_code} without a recognized outcome")
        return PurchaseResult(PurchaseOutcome.UNCERTAIN, provider_reference=request_id,
                              message="VTpass response did not contain a recognized outcome",
                              raw={"code": code, "status": status})

    # ---------------------------------------------------------- requery

    async def requery(self, request_id: str) -> StatusResult:
        """Requery a purchase by request_id (documented recovery path)."""
        if not request_id_is_wellformed(request_id):
            raise VtpassSandboxError("request_id does not match the documented VTpass format")
        base = self.sandbox_base
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.post(f"{base}/requery", headers=self._post_headers(),
                                             json={"request_id": request_id})
        except httpx.HTTPError:
            return StatusResult(recognized=False, message="VTpass requery response was not received")
        try:
            body = response.json()
        except ValueError:
            return StatusResult(recognized=False, message="VTpass requery returned no JSON body")
        code = str(body.get("code") or "")
        transactions = (body.get("content") or {}).get("transactions") \
            if isinstance(body.get("content"), dict) else None
        status = str((transactions or {}).get("status") or "").strip().lower() \
            if isinstance(transactions, dict) else ""
        if code == "015":
            return StatusResult(recognized=False, message="VTpass does not know this request_id")
        if code == "000" and status in _DELIVERED:
            return StatusResult(recognized=True, status="successful")
        if code == "000" and status in _PENDING:
            return StatusResult(recognized=True, status="pending")
        if code in {"016", "040"} and status in _FAILED | {"reversed"}:
            return StatusResult(recognized=True, status="failed")
        return StatusResult(recognized=False, message="VTpass requery returned an unrecognized outcome")

    # ----------------------------------------------------------- shared

    def _json(self, response: httpx.Response, what: str) -> dict:
        try:
            body = response.json()
        except ValueError:
            raise VtpassSandboxError(f"VTpass {what} returned a non-JSON body")
        if not isinstance(body, dict):
            raise VtpassSandboxError(f"VTpass {what} returned an unexpected body")
        if response.status_code == 401 or "invalid credentials" in str(body).lower():
            raise VtpassSandboxError(f"VTpass {what} rejected the credentials")
        return body
