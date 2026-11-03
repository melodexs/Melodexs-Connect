"""Tests for the prepared GN Data adapter (mocked per its published docs).

GN Data has no credentials yet, so these tests lock the adapter to the
documented contract only: endpoint paths, headers (including the
REQUIRED Idempotency-Key), response shapes and outcome normalization.
No test performs a real network call.
"""
import asyncio
from decimal import Decimal

import pytest

from app.config import settings
from app.provider_base import PurchaseOutcome
from app.provider_gndata import (GN_DEFAULT_BASE_URL, GnDataAdapter,
                                 _network_display, _plan_family,
                                 idempotency_key_for)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _run(coro):
    # asyncio.run is safe under pytest: get_event_loop() breaks after
    # earlier test files touch the event loop policy.
    return asyncio.run(coro)


def _fake_client(handler):
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def post(self, path, **kwargs): return await handler(path, **kwargs)
        async def get(self, path, **kwargs): return await handler(path, **kwargs)
    return Client


def _adapter(monkeypatch) -> GnDataAdapter:
    monkeypatch.setattr(settings, "gndata_api_key", "gn_test_key", raising=False)
    return GnDataAdapter()


def test_unconfigured_adapter_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, 'gndata_api_key', None, raising=False)
    assert GnDataAdapter().is_configured() is False


def test_idempotency_key_is_a_stable_uuid_per_reference():
    a, b = idempotency_key_for("REF123"), idempotency_key_for("REF123")
    other = idempotency_key_for("REF124")
    assert a == b and a != other
    import uuid as _uuid
    _uuid.UUID(a)  # raises if not a valid UUID string
    assert len(a) == 36


def test_network_and_family_normalization():
    assert _network_display("MTN Data") == "MTN"
    assert _network_display("9mobile Data") == "9mobile"
    assert _network_display("Unknown Net") is None
    assert _plan_family("SME") == "sme"
    assert _plan_family("Corporate") == "corporate"
    assert _plan_family("Gifting") == "gifting"
    assert _plan_family("Coupon") == "coupon"
    assert _plan_family("") is None
    assert _plan_family(None) is None
    assert _plan_family("Mystery") is None  # never guessed


def test_catalog_normalization_from_documented_shape(monkeypatch):
    async def handler(path, **kwargs):
        assert path == f"{GN_DEFAULT_BASE_URL}/data/services"
        assert kwargs.get("params") == {"include_plans": "true"}
        assert kwargs["headers"]["Authorization"] == "Bearer gn_test_key"
        return FakeResponse(200, [
            {"id": 1, "name": "MTN Data", "available": True,
             "plans": [
                 {"id": 10, "name": "MTN SME 1GB - 30 Days", "network_id": 1,
                  "price": 265.0, "duration": "Monthly", "validity": "30days",
                  "type": "SME", "total_data": "1GB", "available": True},
                 {"id": 11, "name": "MTN 1GB - 30 Days", "network_id": 1,
                  "price": 405.96, "duration": "Monthly", "validity": "30days",
                  "type": "Corporate", "total_data": "1GB", "available": True},
                 {"id": 12, "name": "MTN Weird - 30 Days", "network_id": 1,
                  "price": 100.0, "duration": "Monthly", "validity": "30days",
                  "type": "Whatever", "total_data": "1GB", "available": False},
             ]},
            {"id": 2, "name": "Glo Data", "available": True, "plans": None},
        ])
    async def fake_plans(self, network_id):
        assert network_id == 2
        return [{"id": 687, "name": "1.0 GB", "network_id": 2, "price": 405.96,
                 "duration": "Monthly", "validity": "30days", "type": "Corporate",
                 "total_data": "1GB", "available": True}]
    monkeypatch.setattr("app.provider_gndata.GnDataAdapter._plans_for_network", fake_plans)
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(handler))
    packages = _run(_adapter(monkeypatch).fetch_catalog())
    assert len(packages) == 3
    by_code = {p.code: p for p in packages}
    sme = by_code["1:10"]
    assert sme.network == "MTN" and sme.plan_type == "sme" and sme.data_size == "1GB"
    assert sme.cost == Decimal("265")
    cg = by_code["1:11"]
    assert cg.plan_type == "corporate"
    glo = by_code["2:687"]
    assert glo.network == "Glo" and glo.validity == "30days"
    # Unavailable plans are skipped entirely.
    assert "1:12" not in by_code


def test_purchase_success_sends_idempotency_key_and_maps_reference(monkeypatch):
    async def handler(path, **kwargs):
        assert path == f"{GN_DEFAULT_BASE_URL}/data/purchase"
        headers = kwargs["headers"]
        assert headers["Authorization"] == "Bearer gn_test_key"
        assert headers["Idempotency-Key"] == idempotency_key_for("REF-1")
        assert kwargs["json"] == {"phone": "08031234567", "network_id": 2, "plan_id": 687}
        return FakeResponse(200, {"request_id": "GND_DATA_20260814_99214",
                                  "status": "success", "amount": 405.96,
                                  "transaction_id": "TX_8812903",
                                  "message": "Data purchase successful"})
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(handler))
    result = _run(
        _adapter(monkeypatch).submit_data_purchase(network="Glo", package_code="2:687",
                                        phone="08031234567", reference="REF-1"))
    assert result.outcome == PurchaseOutcome.SUCCESSFUL
    assert result.provider_reference == "GND_DATA_20260814_99214"


def test_purchase_outcome_safety_mapping(monkeypatch):
    cases = [
        (409, {"message": "duplicate"}, PurchaseOutcome.UNCERTAIN),
        (400, {"message": "insufficient wallet balance"}, PurchaseOutcome.FAILED_FINAL),
        (504, {"message": "upstream timeout"}, PurchaseOutcome.UNCERTAIN),
        (500, {"message": "server error"}, PurchaseOutcome.UNCERTAIN),
        (200, {"status": "weird"}, PurchaseOutcome.UNCERTAIN),
    ]
    import httpx
    for status, payload, expected in cases:
        async def handler(path, **kwargs):
            return FakeResponse(status, payload)
        monkeypatch.setattr(httpx, "AsyncClient", _fake_client(handler))
        result = _run(
            _adapter(monkeypatch).submit_data_purchase(network="Glo", package_code="2:687",
                                            phone="08031234567", reference="REF-2"))
        assert result.outcome == expected, (status, result)


def test_purchase_timeout_is_uncertain(monkeypatch):
    monkeypatch.setattr(settings, 'gndata_api_key', 'gn_test_key', raising=False)
    async def handler(path, **kwargs):
        raise TimeoutError()
    import app.provider_gndata as gn
    monkeypatch.setattr(gn.httpx, "AsyncClient", _fake_client(handler))
    settings.gndata_api_key = "gn_test_key"
    result = _run(
        GnDataAdapter().submit_data_purchase(network="Glo", package_code="2:687",
                                              phone="08031234567", reference="REF-3"))
    assert result.outcome == PurchaseOutcome.UNCERTAIN
    assert result.provider_reference is None


def test_purchase_with_invalid_mapping_never_calls_provider(monkeypatch):
    import httpx
    called = []
    def _boom(**kwargs):
        called.append(1)
        raise AssertionError("provider must not be called")
    monkeypatch.setattr(httpx, "AsyncClient", _boom)
    result = _run(
        _adapter(monkeypatch).submit_data_purchase(network="Glo", package_code="not-a-composite",
                                        phone="08031234567", reference="REF-4"))
    assert result.outcome == PurchaseOutcome.FAILED_FINAL
    assert called == []


def test_status_lookup_is_unsupported_and_stays_uncertain(monkeypatch):
    monkeypatch.setattr(settings, "gndata_api_key", "gn_test_key", raising=False)
    result = _run(
        GnDataAdapter().transaction_status("REF-5"))
    # recognized=False forces callers to treat the purchase as uncertain.
    assert result.recognized is False
    assert result.status is None


def test_balance_from_documented_shape(monkeypatch):
    async def handler(path, **kwargs):
        assert path == f"{GN_DEFAULT_BASE_URL}/wallet/balance"
        return FakeResponse(200, {"balance": 15450.0, "currency": "NGN",
                                  "user_id": 42, "email": "developer@example.com"})
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(handler))
    result = _run(_adapter(monkeypatch).account_balance())
    assert result.supported is True
    assert result.balance == Decimal("15450") and result.currency == "NGN"


# ---------------------------------------------------------------------------
# Regression tests added during the 2026-10-18 production-readiness review:
# documented 401 semantics, HTTPS enforcement, redirect rejection, and
# secret-hygiene on every outcome path.
# ---------------------------------------------------------------------------

def test_purchase_401_is_final_failure_never_uncertain(monkeypatch):
    """Docs: 401 = missing/invalid Bearer key. No transaction can be
    created, so it must map to FAILED_FINAL (uncertain would strand a
    purchase with no status endpoint to reconcile it)."""
    async def handler(path, **kwargs):
        return FakeResponse(401, {"detail": "Not authenticated. Provide a valid Bearer token in the Authorization header."})
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(handler))
    result = _run(
        _adapter(monkeypatch).submit_data_purchase(network="MTN", package_code="1:10",
                                                   phone="08031234567", reference="REF-6"))
    assert result.outcome is PurchaseOutcome.FAILED_FINAL
    assert result.provider_reference is None


def test_insecure_base_url_override_rejected_before_any_request(monkeypatch):
    """The docs print an http://localhost base URL (a defect); an http
    override must fail closed BEFORE any request, so the Bearer key can
    never travel over plaintext."""
    monkeypatch.setattr(settings, "gndata_api_key", "gn_test_key", raising=False)
    monkeypatch.setattr(settings, "gndata_base_url", "http://localhost:8002/api/v1", raising=False)
    import httpx
    def _boom(**kwargs):
        raise AssertionError("no HTTP request may be attempted")
    monkeypatch.setattr(httpx, "AsyncClient", _boom)
    result = _run(
        GnDataAdapter().submit_data_purchase(network="MTN", package_code="1:10",
                                             phone="08031234567", reference="REF-7"))
    assert result.outcome is PurchaseOutcome.FAILED_FINAL
    assert "HTTPS" in result.message
    # catalog building must fail closed too, not silently fall back
    with pytest.raises(ValueError):
        _run(GnDataAdapter().fetch_catalog())


def test_redirect_responses_are_not_followed_and_fail_closed(monkeypatch):
    """follow_redirects=False is asserted by construction: a 3xx must
    produce one single request and an uncertain outcome, never a second
    request that could carry the Bearer key to an unexpected host."""
    import httpx
    seen = []
    async def handler(path, **kwargs):
        seen.append((path, kwargs))
        return FakeResponse(302, {"detail": "Moved"})
    class CapturingClient:
        def __init__(self, **kwargs):
            seen.append(("__init__", kwargs))
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def post(self, path, **kwargs): return await handler(path, **kwargs)
        async def get(self, path, **kwargs): return await handler(path, **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", CapturingClient)
    result = _run(
        _adapter(monkeypatch).submit_data_purchase(network="MTN", package_code="1:10",
                                                   phone="08031234567", reference="REF-8"))
    assert result.outcome is PurchaseOutcome.UNCERTAIN
    inits = [s for s in seen if s[0] == "__init__"]
    requests = [s for s in seen if s[0] != "__init__"]
    assert len(inits) == 1 and inits[0][1].get("follow_redirects") is False
    assert len(requests) == 1, "a redirect must not trigger a second request"


def test_no_api_key_leaks_in_any_outcome_path(monkeypatch):
    """Every failure/uncertain path must be reproducible in logs without
    exposing the Bearer key: messages carry provider status only."""
    key = "gn_super_secret_key_xyz"
    monkeypatch.setattr(settings, "gndata_api_key", key, raising=False)
    import httpx
    import app.provider_gndata as gn

    results = []
    # timeout path
    async def boom(path, **kwargs):
        raise TimeoutError("connection timed out")
    monkeypatch.setattr(gn.httpx, "AsyncClient", _fake_client(boom))
    results.append(_run(GnDataAdapter().submit_data_purchase(
        network="MTN", package_code="1:10", phone="0803", reference="REF-9")))
    # 500 path
    async def fivehundred(path, **kwargs):
        return FakeResponse(500, {"message": "server error"})
    monkeypatch.setattr(gn.httpx, "AsyncClient", _fake_client(fivehundred))
    results.append(_run(GnDataAdapter().submit_data_purchase(
        network="MTN", package_code="1:10", phone="0803", reference="REF-10")))
    # balance error path
    monkeypatch.setattr(gn.httpx, "AsyncClient", _fake_client(boom))
    results.append(_run(GnDataAdapter().account_balance()))
    # headers must carry the key, but no result may expose it
    for r in results:
        blob = str(r.message or "") + str(getattr(r, "raw", None) or "")
        assert key not in blob
    headers = GnDataAdapter()._headers(post=True, reference="REF-11")
    assert headers["Authorization"] == f"Bearer {key}"
