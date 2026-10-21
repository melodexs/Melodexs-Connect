"""ISQUAREDATA adapter contract tests (mocked HTTP; no live calls).

Every assertion here is pinned to the official documentation
(https://documenter.getpostman.com/view/11041569/2s8ZDeUea3) and the
public developer price list (isquaredata.com/developer). Nothing in this
module contacts the provider.
"""
import json
from decimal import Decimal

import httpx
import pytest

from app.config import settings
from app.provider_base import PurchaseOutcome
from app.provider_isquaredata import (ISQUARE_BASE_URL, IsquareDataAdapter,
                                      _family_from_service_name,
                                      _network_from_service_name,
                                      _parse_size, _parse_validity)

SERVICES_BODY = [
    {
        "id": 1,
        "name": "MTN SME DATA",
        "plans": [
            {"id": 1, "custom_name": "500MB => ₦130.00", "name": "500MB",
             "enduser_amount": "130.00", "reseller_amount": "113.00",
             "api_amount": "109.50", "is_active": True, "network": 1},
            {"id": 2, "custom_name": "1GB => ₦240.00", "name": "1GB",
             "enduser_amount": "240.00", "reseller_amount": "225.00",
             "api_amount": "218.00", "is_active": True, "network": 1},
        ],
        "is_active": True,
    },
    {
        "id": 3,
        "name": "AIRTEL DATA",
        "plans": [
            {"id": 27, "custom_name": "750 2weeks => ₦475.00",
             "name": "750 2weeks", "enduser_amount": "475.00",
             "reseller_amount": "430.00", "api_amount": "415.00",
             "is_active": True, "network": 3},
            {"id": 99, "custom_name": "hidden", "name": "hidden",
             "enduser_amount": "1.00", "reseller_amount": "1.00",
             "api_amount": "1.00", "is_active": False, "network": 3},
        ],
        "is_active": True,
    },
]


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setattr(settings, "isquaredata_username", "user", raising=False)
    monkeypatch.setattr(settings, "isquaredata_password", "secret", raising=False)
    monkeypatch.setattr(settings, "isquaredata_webhook_url", None, raising=False)
    return IsquareDataAdapter()


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def test_not_configured_without_credentials():
    adapter = IsquareDataAdapter()
    # Fresh settings have no credentials in tests.
    if not adapter.is_configured():
        with pytest.raises(RuntimeError):
            import asyncio
            asyncio.run(adapter.fetch_catalog())


@pytest.mark.asyncio
async def test_catalog_normalizes_service_names_and_api_cost(configured, monkeypatch):
    def handler(request):
        assert request.headers["authorization"].startswith("Basic ")
        assert str(request.url) == f"{ISQUARE_BASE_URL}/data/services/"
        return httpx.Response(200, json=SERVICES_BODY)

    transport = _mock_transport(handler)
    original = httpx.AsyncClient

    class Patched(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Patched)
    packages = await configured.fetch_catalog()
    by_code = {p.code: p for p in packages}
    assert set(by_code) == {"1", "2", "27"}  # inactive plan 99 excluded
    assert by_code["1"].cost == Decimal("109.50")  # api_amount, not retail
    assert by_code["1"].network == "MTN"
    assert by_code["1"].plan_type == "sme"
    assert by_code["1"].data_size == "500MB"
    assert by_code["27"].network == "Airtel"
    assert by_code["27"].data_size == "750MB"
    assert by_code["27"].validity == "14 days"


@pytest.mark.asyncio
async def test_catalog_reports_unmapped_services_instead_of_guessing(configured, monkeypatch):
    body = [{"id": 9, "name": "Mystery Bundle", "plans": [{"id": 5, "name": "1GB",
            "api_amount": "10.00", "is_active": True}], "is_active": True}]
    transport = _mock_transport(lambda request: httpx.Response(200, json=body))
    original = httpx.AsyncClient

    class Patched(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Patched)
    with pytest.raises(ValueError, match="Mystery Bundle"):
        await configured.fetch_catalog()


@pytest.mark.asyncio
async def test_catalog_rejects_malformed_envelope(configured, monkeypatch):
    transport = _mock_transport(lambda request: httpx.Response(200, json={"unexpected": True}))
    original = httpx.AsyncClient

    class Patched(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Patched)
    with pytest.raises(ValueError):
        await configured.fetch_catalog()


@pytest.mark.asyncio
async def test_purchase_never_reports_success_even_on_http_200(configured, monkeypatch):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        # Docs document NO response body for data purchases.
        return httpx.Response(200, json={"detail": "ok"})

    transport = _mock_transport(handler)
    original = httpx.AsyncClient

    class Patched(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Patched)
    result = await configured.submit_data_purchase(
        network="MTN", package_code="1", phone="08163212121", reference="SDFGFD")
    assert result.outcome is PurchaseOutcome.PENDING
    assert captured["url"] == f"{ISQUARE_BASE_URL}/data/buy/"
    assert captured["body"] == {"plan": 1, "phone_number": "08163212121",
                                "reference": "SDFGFD", "disable_validation": False}


@pytest.mark.asyncio
async def test_purchase_timeout_and_errors_are_uncertain(configured, monkeypatch):
    def handler(request):
        raise httpx.ConnectTimeout("boom")

    transport = _mock_transport(handler)
    original = httpx.AsyncClient

    class Patched(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Patched)
    timeout = await configured.submit_data_purchase(
        network="MTN", package_code="1", phone="08163212121", reference="ref-1")
    assert timeout.outcome is PurchaseOutcome.UNCERTAIN

    transport2 = _mock_transport(lambda r: httpx.Response(
        400, json={"plan_id": ["Insufficient balance to perform transaction!"]}))
    class Patched2(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport2
            super().__init__(*a, **kw)
    monkeypatch.setattr(httpx, "AsyncClient", Patched2)
    rejected = await configured.submit_data_purchase(
        network="MTN", package_code="1", phone="08163212121", reference="ref-2")
    assert rejected.outcome is PurchaseOutcome.UNCERTAIN


@pytest.mark.asyncio
async def test_purchase_does_not_leak_credentials_in_messages(configured, monkeypatch):
    transport = _mock_transport(lambda r: httpx.Response(500, text="upstream error"))
    original = httpx.AsyncClient

    class Patched(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Patched)
    result = await configured.submit_data_purchase(
        network="MTN", package_code="1", phone="08163212121", reference="ref-3")
    assert "secret" not in result.message.lower()
    assert "basic" not in result.message.lower()


@pytest.mark.asyncio
async def test_status_normalization_and_unrecognized_values(configured, monkeypatch):
    def make(status, code=200, reference="ref-9"):
        return lambda r: httpx.Response(code, json={"reference": reference, "status": status})

    async def run(handler):
        transport = _mock_transport(handler)
        original = httpx.AsyncClient
        class Patched(original):
            def __init__(self, *a, **kw):
                kw["transport"] = transport
                super().__init__(*a, **kw)
        return Patched

    original = httpx.AsyncClient
    for status, expected in (("success", "successful"), ("failed", "failed"),
                             ("pending", "pending")):
        class Patched(original):
            def __init__(self, *a, **kw):
                kw["transport"] = _mock_transport(make(status))
                super().__init__(*a, **kw)
        monkeypatch.setattr(httpx, "AsyncClient", Patched)
        result = await configured.transaction_status("ref-9")
        assert result.recognized is True and result.status == expected

    class Patched2(original):
        def __init__(self, *a, **kw):
            kw["transport"] = _mock_transport(make("credited"))
            super().__init__(*a, **kw)
    monkeypatch.setattr(httpx, "AsyncClient", Patched2)
    unknown = await configured.transaction_status("ref-9")
    assert unknown.recognized is False

    class Patched3(original):
        def __init__(self, *a, **kw):
            kw["transport"] = _mock_transport(lambda r: httpx.Response(404, json={}))
            super().__init__(*a, **kw)
    monkeypatch.setattr(httpx, "AsyncClient", Patched3)
    missing = await configured.transaction_status("ref-9")
    assert missing.recognized is False


@pytest.mark.asyncio
async def test_balance_reports_wallet_balance(configured, monkeypatch):
    transport = _mock_transport(lambda r: httpx.Response(
        200, json={"wallet_balance": 10.75, "referral_balance": 0}))
    original = httpx.AsyncClient

    class Patched(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Patched)
    result = await configured.account_balance()
    assert result.supported and result.balance == Decimal("10.75")


@pytest.mark.asyncio
async def test_airtime_is_not_implemented(configured):
    with pytest.raises(NotImplementedError):
        await configured.submit_airtime_purchase(
            network="MTN", phone="08163212121", amount=Decimal("100"), reference="r")


def test_adapter_is_conservative_by_default():
    adapter = IsquareDataAdapter()
    assert adapter.auto_refunds_on_failure is False
    assert adapter.failure_status_is_final is False
    assert adapter.selection_excluded is False
    assert "data" in adapter.capabilities


def test_name_helpers():
    assert _network_from_service_name("MTN SME DATA") == "MTN"
    assert _network_from_service_name("AIRTEL DATA") == "Airtel"
    assert _network_from_service_name("GLO CORPORATE DATA") == "Glo"
    assert _network_from_service_name("9MOBILE T2 DATA") == "9mobile"
    assert _network_from_service_name("Mystery") is None
    assert _family_from_service_name("MTN SME DATA") == "sme"
    assert _family_from_service_name("MTN GIFTING DATA") == "gifting"
    assert _family_from_service_name("AIRTEL DATA") is None
    assert _parse_size("750 2weeks") == "750MB"
    assert _parse_size("1.5GB Weekly") == "1.5GB"
    assert _parse_validity("750 2weeks") == "14 days"
    assert _parse_validity("7GB WEEKLY") == "7 days"
    assert _parse_validity("10GB MONTHLY") == "30 days"
    assert _parse_validity("150MB+ 100MB DAILY") == "1 day"
