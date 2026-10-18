"""MELE DATA adapter contract + sandbox safety tests (MOCKED - no network).

Verified against the official documentation (2026-10-18):
- X-API-Key auth, one base URL, plan_id is an int purchase key,
- reference-based idempotency in the request body (max 80 chars),
- documented auto-refund on carrier rejection (FAILED_FINAL, no
  independent duplicate refund by the platform),
- 409 duplicate_reference proves usage, not outcome (UNCERTAIN),
- requery recognizes ONLY "delivered" and "failed",
- wallet reports mode/livemode; MELEDATA_TEST_MODE fails closed on a
  live or inconsistent mode,
- no webhook / transaction-history support exists (never invented).
"""
import asyncio
from decimal import Decimal

import pytest

from app import provider_meledata
from app.config import settings
from app.provider_base import PurchaseOutcome
from app.provider_meledata import MeleDataAdapter

API_KEY = "mele_test_" + "k" * 24


class _Response:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self._text = text

    def json(self):
        if self._text is not None:
            raise ValueError("no json")
        return self._body

    def raise_for_status(self):
        return None


class _FakeClient:
    responses: list = []
    instances: list = []

    def __init__(self, **kwargs):
        self.options = kwargs
        self.calls = []
        _FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def _handle(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = _Response()
        if _FakeClient.responses:
            response = _FakeClient.responses.pop(0)
        return response

    async def get(self, url, **kwargs):
        return await self._handle("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return await self._handle("POST", url, **kwargs)


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    _FakeClient.responses = []
    _FakeClient.instances = []
    monkeypatch.setattr(provider_meledata.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(settings, "meledata_api_key", API_KEY)
    monkeypatch.setattr(settings, "meledata_test_mode", False)
    yield
    _FakeClient.responses = []


def queue(*responses):
    _FakeClient.responses.extend(responses)


def _set_test_mode(value: bool):
    settings.meledata_test_mode = value


# ------------------------------------------------------------ config

def test_configured_only_with_a_key():
    adapter = MeleDataAdapter()
    monkey = pytest.MonkeyPatch()
    monkey.setattr(settings, "meledata_api_key", None)
    try:
        assert adapter.is_configured() is False
    finally:
        monkey.undo()
    assert MeleDataAdapter().is_configured() is True


# ------------------------------------------------------------ catalog

def test_catalog_uses_documented_fields_and_int_plan_ids():
    queue(_Response(body={"status": True, "message": "ok", "data": {"plans": [
        {"plan_id": 1, "plan_code": "MTN_1GB_SME", "network": "MTN",
         "plan_name": "MTN SME 1GB", "data_size": "1GB", "validity": "30 days",
         "price": 350},
        {"plan_id": 5, "plan_code": "GLO_2GB", "network": "GLO",
         "plan_name": "GLO 2GB", "data_size": "2GB", "validity": "30 days",
         "price": "720.50"},
    ]}}))
    packages = asyncio.run(MeleDataAdapter().fetch_catalog())
    assert [p.code for p in packages] == ["1", "5"]  # plan_id as purchase key
    assert packages[0].plan_type == "sme"
    assert packages[1].plan_type is None  # unknown family stays unmatched
    assert str(packages[1].cost) == "720.50"
    assert packages[0].network == "MTN"
    call = _FakeClient.instances[0].calls[0]
    assert call[1].endswith("/data/plans")
    assert call[2]["headers"]["X-API-Key"] == API_KEY


def test_catalog_rejects_legacy_and_invalid_envelopes():
    # The originally assumed shape (top-level "plans") is NOT what the live
    # API returns; the adapter must reject it instead of guessing.
    queue(_Response(body={"plans": [{"plan_id": 1, "plan_code": "X", "price": 5}]}))
    with pytest.raises(ValueError):
        asyncio.run(MeleDataAdapter().fetch_catalog())
    queue(_Response(body={"status": False, "message": "error", "data": None}))
    with pytest.raises(ValueError):
        asyncio.run(MeleDataAdapter().fetch_catalog())


def test_catalog_rejects_unknown_networks():
    queue(_Response(body={"status": True, "data": {"plans": [
        {"plan_id": 1, "plan_code": "X", "network": "SMILE",
         "plan_name": "X", "price": 5}]}}))
    with pytest.raises(ValueError):
        asyncio.run(MeleDataAdapter().fetch_catalog())


def test_catalog_rejects_string_plan_ids_and_duplicates():
    queue(_Response(body={"status": True, "data": {"plans": [
        {"plan_id": "1", "plan_code": "X", "price": 5}]}}))
    with pytest.raises(ValueError):
        asyncio.run(MeleDataAdapter().fetch_catalog())
    queue(_Response(body={"status": True, "data": {"plans": [
        {"plan_id": 1, "plan_code": "A", "price": 5},
        {"plan_id": 1, "plan_code": "B", "price": 6}]}}))
    with pytest.raises(ValueError):
        asyncio.run(MeleDataAdapter().fetch_catalog())


# ----------------------------------------------------------- purchases

def test_purchase_success_mapping_and_payload():
    queue(_Response(body={"status": True, "message": "Transaction successful",
                          "data": {"status": "success", "reference": "ref-1"}}))
    result = asyncio.run(MeleDataAdapter().submit_data_purchase(
        network="MTN", package_code="12", phone="08012345678", reference="ref-1"))
    assert result.outcome is PurchaseOutcome.SUCCESSFUL
    assert result.provider_reference == "ref-1"
    call = _FakeClient.instances[0].calls[0]
    assert call[1].endswith("/data/purchase")
    payload = call[2]["json"]
    assert payload["plan_id"] == 12          # documented int type
    assert isinstance(payload["plan_id"], int)
    assert payload["network"] == "MTN"
    assert payload["phone_number"] == "08012345678"
    assert payload["reference"] == "ref-1"   # body idempotency key
    headers = call[2]["headers"]
    assert headers["X-API-Key"] == API_KEY
    assert "Authorization" not in headers


def test_purchase_failed_is_final_because_refund_is_documented():
    queue(_Response(body={"status": False, "message": "Carrier rejected",
                          "data": {"status": "failed"}}))
    result = asyncio.run(MeleDataAdapter().submit_data_purchase(
        network="Glo", package_code="3", phone="08123456780", reference="ref-2"))
    # Documented automatic wallet refund -> FAILED_FINAL without any
    # platform-issued duplicate refund.
    assert result.outcome is PurchaseOutcome.FAILED_FINAL


def test_purchase_duplicate_reference_is_uncertain():
    queue(_Response(status_code=409, body={"status": False, "message": "duplicate_reference"}))
    result = asyncio.run(MeleDataAdapter().submit_data_purchase(
        network="Glo", package_code="3", phone="08123456780", reference="ref-3"))
    assert result.outcome is PurchaseOutcome.UNCERTAIN
    assert "reconciliation" in result.message.lower()


def test_purchase_timeout_is_uncertain_and_never_confirms_failure():
    class _BoomClient(_FakeClient):
        async def post(self, url, **kwargs):
            raise provider_meledata.httpx.ConnectTimeout("nope")
    provider_meledata.httpx.AsyncClient = _BoomClient
    result = asyncio.run(MeleDataAdapter().submit_data_purchase(
        network="MTN", package_code="1", phone="08012345678", reference="ref-4"))
    assert result.outcome is PurchaseOutcome.UNCERTAIN


def test_purchase_malformed_body_and_server_error_are_uncertain():
    queue(_Response(text=""))  # non-JSON
    result = asyncio.run(MeleDataAdapter().submit_data_purchase(
        network="MTN", package_code="1", phone="08012345678", reference="ref-5"))
    assert result.outcome is PurchaseOutcome.UNCERTAIN
    queue(_Response(status_code=500, body={"status": False, "message": "server_error"}))
    result = asyncio.run(MeleDataAdapter().submit_data_purchase(
        network="MTN", package_code="1", phone="08012345678", reference="ref-6"))
    assert result.outcome is PurchaseOutcome.UNCERTAIN


def test_purchase_rejects_oversized_and_empty_references():
    result = asyncio.run(MeleDataAdapter().submit_data_purchase(
        network="MTN", package_code="1", phone="08012345678", reference="r" * 81))
    assert result.outcome is PurchaseOutcome.UNCERTAIN
    assert _FakeClient.instances == []  # refused before any HTTP call
    result = asyncio.run(MeleDataAdapter().submit_data_purchase(
        network="MTN", package_code="1", phone="08012345678", reference=""))
    assert result.outcome is PurchaseOutcome.UNCERTAIN


def test_airtime_purchase_minimum_and_mapping():
    queue(_Response(body={"status": True, "data": {"status": "success"}}))
    result = asyncio.run(MeleDataAdapter().submit_airtime_purchase(
        network="Airtel", phone="08012345678", amount=Decimal("150"), reference="ref-a1"))
    assert result.outcome is PurchaseOutcome.SUCCESSFUL
    call = _FakeClient.instances[0].calls[0]
    assert call[1].endswith("/airtime/purchase")
    assert call[2]["json"]["amount"] == 150.0
    # Documented minimum of 100 is enforced before any request.
    _FakeClient.instances.clear()
    result = asyncio.run(MeleDataAdapter().submit_airtime_purchase(
        network="Airtel", phone="08012345678", amount=Decimal("50"), reference="ref-a2"))
    assert result.outcome is PurchaseOutcome.UNCERTAIN
    assert _FakeClient.instances == []


# ------------------------------------------------------------- requery

def test_requery_recognizes_only_documented_statuses():
    adapter = MeleDataAdapter()
    for status_value, expected in [("delivered", ("successful", True)),
                                   ("failed", ("failed", True)),
                                   ("processing", (None, False)),
                                   ("", (None, False))]:
        queue(_Response(body={"success": True, "data": {"status": status_value}}))
        outcome = asyncio.run(adapter.transaction_status("ref-1"))
        assert (outcome.status, outcome.recognized) == expected, status_value
    # "pending"/"processing" are NOT documented requery statuses for MELE:
    # an undocumented value must never be treated as final.
    queue(_Response(status_code=404, body={"status": False, "message": "not_found"}))
    outcome = asyncio.run(adapter.transaction_status("missing"))
    assert outcome.recognized is False
    call = _FakeClient.instances[-1].calls[0]
    assert call[2]["params"] == {"ref": "missing"}


# ------------------------------------------------------------- balance

def test_balance_parses_mode_and_livemode():
    queue(_Response(body={"success": True, "data": {"balance": 14250.50, "currency": "NGN",
                                                    "livemode": False, "mode": "test"}}))
    result = asyncio.run(MeleDataAdapter().account_balance())
    assert result.supported and result.balance == Decimal("14250.5")
    assert result.currency == "NGN" and result.mode == "test" and result.livemode is False


def test_test_mode_guard_fails_closed_on_live_credentials():
    import pytest as _pytest
    monkey = _pytest.MonkeyPatch()
    monkey.setattr(settings, "meledata_test_mode", True)
    try:
        # Provider reports a LIVE wallet: refuse everything.
        queue(_Response(body={"success": True, "data": {"balance": 1, "currency": "NGN",
                                                        "livemode": True, "mode": "live"}}))
        result = asyncio.run(MeleDataAdapter().account_balance())
        assert result.supported is False
        assert "refusing" in result.message
        # Purchase path also fails closed without a purchase request.
        result = asyncio.run(MeleDataAdapter().submit_data_purchase(
            network="MTN", package_code="1", phone="08012345678", reference="ref-live"))
        assert result.outcome is PurchaseOutcome.UNCERTAIN
        purchase_calls = [c for i in _FakeClient.instances for c in i.calls]
        assert all("/data/purchase" not in c[1] for c in purchase_calls)
        # Inconsistent indicators (mode test but livemode true) also fail.
        queue(_Response(body={"success": True, "data": {"balance": 1, "currency": "NGN",
                                                        "livemode": True, "mode": "test"}}))
        result = asyncio.run(MeleDataAdapter().account_balance())
        assert result.supported is False
        # A consistent test wallet passes the guard.
        queue(_Response(body={"success": True, "data": {"balance": 5000, "currency": "NGN",
                                                        "livemode": False, "mode": "test"}}))
        ok = asyncio.run(MeleDataAdapter().account_balance())
        assert ok.supported and ok.mode == "test"
    finally:
        monkey.undo()


def test_test_mode_guard_blocks_when_wallet_unreachable():
    import pytest as _pytest
    monkey = _pytest.MonkeyPatch()
    monkey.setattr(settings, "meledata_test_mode", True)
    try:
        queue(_Response(text=""))  # wallet call fails
        result = asyncio.run(MeleDataAdapter().submit_data_purchase(
            network="MTN", package_code="1", phone="08012345678", reference="ref-x"))
        assert result.outcome is PurchaseOutcome.UNCERTAIN
        purchase_calls = [c for i in _FakeClient.instances for c in i.calls]
        assert all("/data/purchase" not in c[1] for c in purchase_calls)
    finally:
        monkey.undo()


# --------------------------------------------------------- capabilities

def test_redirect_responses_are_not_followed_and_fail_closed():
    """MELE 308-redirects its trailing-slash endpoints; the adapter must
    call the final URLs, never follow a redirect, and treat a 3xx body
    as an error/uncertain outcome (verified live: the slash forms
    redirect and return an HTML stub)."""
    queue(_Response(status_code=308, text="Redirecting..."))
    result = asyncio.run(MeleDataAdapter().submit_data_purchase(
        network="MTN", package_code="553", phone="08031234567", reference="ref-1"))
    assert result.outcome is PurchaseOutcome.UNCERTAIN
    fake = _FakeClient.instances[0]
    assert fake.options.get("follow_redirects") is False
    assert len(fake.calls) == 1, "a redirect response must not trigger a second request"

    queue(_Response(status_code=308, text="Redirecting..."))
    balance = asyncio.run(MeleDataAdapter().account_balance())
    assert balance.balance is None, "a redirect body must never parse as a balance"

    queue(_Response(status_code=308, text="Redirecting..."))
    status = asyncio.run(MeleDataAdapter().transaction_status("ref-1"))
    assert status.recognized is False


def test_redirect_body_cannot_satisfy_the_test_mode_gate():
    """Even if a redirect/HTML stub sneaks in, the MELEDATA_TEST_MODE
    wallet gate must fail closed on an unreadable mode."""
    _set_test_mode(True)
    queue(_Response(status_code=308, text="Redirecting..."))
    refusal = asyncio.run(MeleDataAdapter()._test_mode_gate())
    assert refusal is not None
    queue(_Response(status_code=308, text="Redirecting..."))
    result = asyncio.run(MeleDataAdapter().submit_data_purchase(
        network="MTN", package_code="553", phone="08031234567", reference="ref-2"))
    assert result.outcome is PurchaseOutcome.UNCERTAIN
    assert result.message and "fail" in result.message.lower()


def test_request_urls_are_the_final_no_trailing_slash_forms():
    """Regression: /wallet and /data/status must be called WITHOUT the
    trailing slash (the slash forms 308-redirect; the adapter must not
    depend on redirect following)."""
    queue(_Response(body={"success": True, "data": {"balance": 5.0, "currency": "NGN",
                                                    "mode": "test", "livemode": False}}))
    asyncio.run(MeleDataAdapter().account_balance())
    assert _FakeClient.instances[-1].calls[0][1].endswith("/wallet")
    assert not _FakeClient.instances[-1].calls[0][1].endswith("/wallet/")
    queue(_Response(body={"success": True, "data": {"status": "delivered"}}))
    asyncio.run(MeleDataAdapter().transaction_status("ref-3"))
    assert _FakeClient.instances[-1].calls[0][1].endswith("/data/status")
    assert not _FakeClient.instances[-1].calls[0][1].endswith("/data/status/")


def test_no_webhook_or_history_capabilities_are_claimed():
    adapter = MeleDataAdapter()
    assert "webhooks" not in adapter.capabilities
    assert "history" not in adapter.capabilities
    assert "catalog" in adapter.capabilities and "balance" in adapter.capabilities
    describe = adapter.describe()
    assert describe["configured"] is True
    assert describe["auto_refunds_on_failure"] is True


def test_secrets_never_appear_in_results():
    queue(_Response(status_code=401, body={"status": False, "message": "invalid_token"}))
    result = asyncio.run(MeleDataAdapter().submit_data_purchase(
        network="MTN", package_code="1", phone="08012345678", reference="ref-s"))
    assert result.outcome is PurchaseOutcome.UNCERTAIN
    assert API_KEY not in result.message
