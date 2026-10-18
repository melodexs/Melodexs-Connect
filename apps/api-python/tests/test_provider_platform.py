"""Tests for the multi-provider fulfillment platform.

Covers:
- adapter outcome normalization (MELE DATA + RizPay, mocked per their
  published documentation formats),
- WiseSub backward compatibility through the registry,
- package equivalence matching,
- supplier price comparison (Decimal, overrides, availability),
- provider enablement rules and admin authorization,
- routing gates and safe fallback decisions,
- migration/schema compatibility.
"""
import asyncio
import json
import secrets
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app import admin_routes, main
from app.config import settings
from app.database import db_session, q
from app.package_matching import package_key, size_to_mb, validity_to_days
from app.price_comparison import compare_suppliers
from app.provider_base import PurchaseOutcome
from app.provider_meledata import MeleDataAdapter, _plan_family
from app.provider_registry import (ensure_provider_rows, provider_enabled,
                                   resolve_fulfillment_provider,
                                   safe_fallback_candidate)
from app.provider_rizpay import RizPayAdapter
from app.provider_wisesub import WiseSubAdapter


# --------------------------------------------------------------------------
# Package equivalence
# --------------------------------------------------------------------------

def test_size_and_validity_normalization():
    assert size_to_mb("1GB") == Decimal(1024)
    assert size_to_mb("500MB") == Decimal(500)
    assert size_to_mb("250 KB") == Decimal("0.25")
    assert size_to_mb(None) is None
    assert size_to_mb("unlimited") is None
    assert validity_to_days("30 days") == 30
    assert validity_to_days("7 Days") == 7
    assert validity_to_days("2 weeks") == 14
    assert validity_to_days("1 month") == 30
    assert validity_to_days("Monthly") == 30
    assert validity_to_days(None) is None
    assert validity_to_days("forever") is None


def test_equivalence_requires_all_known_attributes():
    full = package_key(network="MTN", data_size="1GB", validity="30 days", plan_type="SME")
    assert full is not None
    same = package_key(network="mtn", data_size="1024MB", validity="1 month", plan_type="sme")
    assert full.matches(same)
    # Different family never matches.
    corporate = package_key(network="MTN", data_size="1GB", validity="30 days", plan_type="corporate")
    assert not full.matches(corporate)
    # Unknown family is ineligible for automatic matching (never guessed).
    unknown_family = package_key(network="MTN", data_size="1GB", validity="30 days", plan_type=None)
    assert unknown_family is None
    # Missing size or validity is ineligible.
    assert package_key(network="MTN", data_size=None, validity="30 days", plan_type="SME") is None
    assert package_key(network="MTN", data_size="1GB", validity=None, plan_type="SME") is None
    # Different network/size/validity never match.
    assert not full.matches(package_key(network="Glo", data_size="1GB", validity="30 days", plan_type="SME"))
    assert not full.matches(package_key(network="MTN", data_size="2GB", validity="30 days", plan_type="SME"))
    assert not full.matches(package_key(network="MTN", data_size="1GB", validity="7 days", plan_type="SME"))


def test_mele_plan_family_extraction():
    assert _plan_family("MTN_1GB_SME MTN SME 1GB") == "sme"
    assert _plan_family("MTN_1GB_CG Corporate") == "corporate"
    assert _plan_family("GLO_2GB GLO 2GB") is None  # family must be named, never guessed


# --------------------------------------------------------------------------
# Adapter outcome normalization (mocked per published doc formats)
# --------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_mele_purchase_success_and_autorefunded_failure(monkeypatch):
    adapter = MeleDataAdapter()
    monkeypatch.setattr(settings, "meledata_api_key", "mele_test_key", raising=False)
    # Pin test mode OFF: this test exercises the purchase mapping itself and
    # must not inherit a developer's live-verification MELEDATA_TEST_MODE env.
    monkeypatch.setattr(settings, "meledata_test_mode", False, raising=False)

    async def ok_purchase(path, **kwargs):
        return FakeResponse(200, {"status": True, "message": "Transaction successful",
                                  "data": {"status": "success", "reference": "ref-1", "amount": 290.0}})
    monkeypatch.setattr("app.provider_meledata.httpx.AsyncClient", _fake_client(ok_purchase))
    result = asyncio.run(adapter.submit_data_purchase(network="MTN", package_code="1", phone="09012345678", reference="ref-1"))
    assert result.outcome is PurchaseOutcome.SUCCESSFUL and result.provider_reference == "ref-1"

    async def failed_purchase(path, **kwargs):
        return FakeResponse(200, {"status": False, "message": "Provider error: plan temporarily unavailable",
                                   "data": {"status": "failed", "reference": "ref-2", "amount": 290.0}})
    monkeypatch.setattr("app.provider_meledata.httpx.AsyncClient", _fake_client(failed_purchase))
    result = asyncio.run(adapter.submit_data_purchase(network="MTN", package_code="1", phone="09012345678", reference="ref-2"))
    # MELE documents automatic refunds on failure -> final failure, safe to refund.
    assert result.outcome is PurchaseOutcome.FAILED_FINAL

    async def duplicate(path, **kwargs):
        return FakeResponse(409, {"status": False, "message": "duplicate_reference"})
    monkeypatch.setattr("app.provider_meledata.httpx.AsyncClient", _fake_client(duplicate))
    result = asyncio.run(adapter.submit_data_purchase(network="MTN", package_code="1", phone="09012345678", reference="ref-2"))
    # A duplicate proves usage, never fulfillment.
    assert result.outcome is PurchaseOutcome.UNCERTAIN

    async def boom(path, **kwargs):
        raise httpx.ReadTimeout("lost")
    monkeypatch.setattr("app.provider_meledata.httpx.AsyncClient", _fake_client(boom))
    result = asyncio.run(adapter.submit_data_purchase(network="MTN", package_code="1", phone="09012345678", reference="ref-3"))
    assert result.outcome is PurchaseOutcome.UNCERTAIN


def test_mele_status_normalization(monkeypatch):
    adapter = MeleDataAdapter()
    monkeypatch.setattr(settings, "meledata_api_key", "mele_test_key", raising=False)

    async def delivered(path, **kwargs):
        return FakeResponse(200, {"success": True, "data": {"status": "delivered"}})
    monkeypatch.setattr("app.provider_meledata.httpx.AsyncClient", _fake_client(delivered))
    assert asyncio.run(adapter.transaction_status("ref-1")).status == "successful"

    async def failed(path, **kwargs):
        return FakeResponse(200, {"success": True, "data": {"status": "failed"}})
    monkeypatch.setattr("app.provider_meledata.httpx.AsyncClient", _fake_client(failed))
    assert asyncio.run(adapter.transaction_status("ref-2")).status == "failed"

    async def weird(path, **kwargs):
        return FakeResponse(200, {"success": True, "data": {"status": "quantum"}})
    monkeypatch.setattr("app.provider_meledata.httpx.AsyncClient", _fake_client(weird))
    outcome = asyncio.run(adapter.transaction_status("ref-3"))
    assert outcome.recognized is False  # unrecognized -> uncertain, never success/failure


def test_rizpay_pending_acceptance_and_duplicate_reference(monkeypatch):
    adapter = RizPayAdapter()
    monkeypatch.setattr(settings, "rizpay_api_key", "rzp_test", raising=False)

    async def accepted_pending(path, **kwargs):
        return FakeResponse(200, {"data": {"id": 42, "attributes": {"status": "pending"}}})
    monkeypatch.setattr("app.provider_rizpay.httpx.AsyncClient", _fake_client(accepted_pending))
    result = asyncio.run(adapter.submit_data_purchase(network="MTN", package_code="9", phone="08011111111", reference="ord-1"))
    # Accepted but not delivered: pending, never successful.
    assert result.outcome is PurchaseOutcome.PENDING and result.provider_reference == "42"

    async def delivered(path, **kwargs):
        return FakeResponse(200, {"data": {"id": 43, "attributes": {"status": "successful"}}})
    monkeypatch.setattr("app.provider_rizpay.httpx.AsyncClient", _fake_client(delivered))
    result = asyncio.run(adapter.submit_data_purchase(network="MTN", package_code="9", phone="08011111111", reference="ord-2"))
    assert result.outcome is PurchaseOutcome.SUCCESSFUL

    async def duplicate(path, **kwargs):
        return FakeResponse(409, {"code": "DUPLICATE_REFERENCE"})
    monkeypatch.setattr("app.provider_rizpay.httpx.AsyncClient", _fake_client(duplicate))
    result = asyncio.run(adapter.submit_data_purchase(network="MTN", package_code="9", phone="08011111111", reference="ord-2"))
    assert result.outcome is PurchaseOutcome.UNCERTAIN


def test_wisesub_adapter_never_emits_final_failure(monkeypatch):
    adapter = WiseSubAdapter()
    async def rejected(path, **kwargs):
        return FakeResponse(400, {"success": False, "message": "insufficient balance"})
    monkeypatch.setattr("app.providers.httpx.AsyncClient", _fake_client(rejected))
    result = asyncio.run(adapter.submit_data_purchase(network="MTN", package_code="mtn-x", phone="08011111111", reference="ref-9"))
    # WiseSub documents no automatic refunds: a rejection is uncertain,
    # resolved through reconciliation, exactly like the main purchase flow.
    assert result.outcome is PurchaseOutcome.UNCERTAIN
    assert adapter.is_configured() if settings.wisesub_api_key else True


def _fake_client(handler):
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def post(self, path, **kwargs): return await handler(path, **kwargs)
        async def get(self, path, **kwargs): return await handler(path, **kwargs)
    return Client


# --------------------------------------------------------------------------
# Registry: enablement, routing gates and safe fallback
# --------------------------------------------------------------------------

def test_registry_defaults_and_wisesub_protection():
    with db_session() as db:
        q(db, "UPDATE providers SET enabled=0 WHERE slug='meledata'")
    ensure_provider_rows()
    assert provider_enabled("wisesub") is True
    assert provider_enabled("meledata") is False
    assert provider_enabled("rizpay") is False
    assert provider_enabled("gndata") is False
    # Routing disabled: only wisesub resolves.
    assert resolve_fulfillment_provider("wisesub").slug == "wisesub"
    with pytest.raises(RuntimeError):
        resolve_fulfillment_provider("meledata")
    # Fallback never triggers while routing is disabled.
    assert safe_fallback_candidate(current_provider="wisesub", outcome="failed_final", plan_source="wisesub") is None


def test_fallback_requires_known_final_outcome_and_refunds(monkeypatch):
    ensure_provider_rows()
    monkeypatch.setattr(settings, "multi_provider_routing_enabled", True, raising=False)
    monkeypatch.setattr(settings, "meledata_api_key", "mele_test_key", raising=False)
    monkeypatch.setattr(settings, "wisesub_api_key", "ws-key", raising=False)
    monkeypatch.setattr(settings, "wisesub_api_secret", "ws-secret", raising=False)
    with db_session() as db:
        q(db, "UPDATE providers SET enabled=1 WHERE slug='meledata'")
    # Uncertain or pending outcomes never trigger a fallback.
    assert safe_fallback_candidate(current_provider="wisesub", outcome="uncertain", plan_source="wisesub") is None
    assert safe_fallback_candidate(current_provider="wisesub", outcome="pending", plan_source="wisesub") is None
    # WiseSub failures never auto-fallback: no documented refunds.
    assert safe_fallback_candidate(current_provider="wisesub", outcome="failed_final", plan_source="wisesub") is None
    # A provider with documented auto-refunds may fall back safely.
    assert safe_fallback_candidate(current_provider="meledata", outcome="failed_final", plan_source="meledata") == "wisesub"
    with db_session() as db:
        q(db, "UPDATE providers SET enabled=0 WHERE slug='meledata'")


# --------------------------------------------------------------------------
# Supplier price comparison (read-only, Decimal-safe)
# --------------------------------------------------------------------------

@pytest.fixture
def comparison_plans():
    suffix = secrets.token_hex(4)
    with db_session() as db:
        ids = []
        for source, code, cost, price, available, size, validity in (
                ("wisesub", f"mtn-cmp-w-{suffix}", 485.0, 495.0, 1, "1GB", "30 Days"),
                ("wisesub", f"mtn-cmp-w2-{suffix}", 990.0, 1010.0, 1, "2GB", "7 Days"),
                ("meledata", f"mtn-cmp-m-{suffix}", 470.0, 495.0, 0, "1GB", "30 Days"),
        ):
            ids.append(q(db, """INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,
                category,provider,provider_code,provider_package_code,data_size,validity,source,provider_available)
                VALUES('MTN',:plan,:cost,:price,1,'Monthly Plans',:source,'mtn',:code,:size,:validity,:source,:available)
                RETURNING id""",
                {"plan": f"Cmp {source} {code}", "cost": cost, "price": price,
                 "source": source, "code": code, "available": available,
                 "size": size, "validity": validity}).scalar())
    yield suffix
    with db_session() as db:
        for plan_id in ids:
            q(db, "DELETE FROM data_plans WHERE id=:id", {"id": plan_id})


def test_price_comparison_is_read_only_and_decimal_safe(comparison_plans):
    before = _catalog_snapshot()
    groups = compare_suppliers("MTN", {"wisesub"})
    mine = [g for g in groups if g.size_mb == Decimal(1024) and g.validity_days == 30 and g.cheapest_available]
    assert mine, "expected the seeded 1GB/30-day group"
    group = mine[0]
    quotes = {quote.provider: quote for quote in group.quotes}
    # Comparison reads current supplier costs, never hard-coded prices.
    assert quotes["wisesub"].supplier_cost == Decimal("485.0")
    # A disabled provider is shown but never available for routing.
    assert quotes["meledata"].available is False
    # Cheapest available respects eligibility (only wisesub eligible here).
    assert group.cheapest_available.provider == "wisesub"
    # Automatic equivalence stays disabled without provider family labels.
    assert group.eligible is False and "family" in group.reason
    # No purchase side effects: catalog untouched.
    assert _catalog_snapshot() == before


def _catalog_snapshot():
    with db_session() as db:
        return q(db, "SELECT COUNT(*) FROM data_plans").scalar(), q(db, "SELECT COUNT(*) FROM transactions WHERE type='debit'").scalar()


# --------------------------------------------------------------------------
# Admin endpoints: authorization + provider management
# --------------------------------------------------------------------------

def _admin_client(client):
    suffix = secrets.token_hex(4)
    response = client.post("/api/register", json={"name": "Prov Admin",
        "email": f"provadmin-{suffix}@example.com", "phone": f"083{int(suffix,16)%10**8:08d}",
        "password": "password123"})
    user_id = response.json()["user"]["id"]
    with db_session() as db:
        q(db, "UPDATE users SET is_admin=1 WHERE id=:id", {"id": user_id})
    return client


def test_provider_endpoints_require_admin():
    with TestClient(main.app) as client:
        client.post("/api/register", json={"name": "Plain", "email": f"plainp-{secrets.token_hex(4)}@example.com",
            "phone": f"082{int(secrets.token_hex(4),16)%10**8:08d}", "password": "password123"})
        assert client.get("/api/admin/providers").status_code == 403
        assert client.patch("/api/admin/providers/meledata", json={"enabled": True}).status_code == 403
        assert client.post("/api/admin/providers/meledata/health-check").status_code == 403
        assert client.get("/api/admin/providers/price-comparison?network=MTN").status_code == 403


def test_wisesub_cannot_be_disabled_and_unconfigured_cannot_be_enabled(monkeypatch):
    # Isolate from live-verification env vars: this test asserts the
    # unconfigured-provider enable guard and must not see a developer's
    # MELEDATA_API_KEY / MELEDATA_TEST_MODE settings.
    monkeypatch.setattr(settings, "meledata_api_key", None, raising=False)
    monkeypatch.setattr(settings, "meledata_test_mode", False, raising=False)
    with TestClient(main.app) as client:
        _admin_client(client)
        blocked = client.patch("/api/admin/providers/wisesub", json={"enabled": False})
        assert blocked.status_code == 409
        unavailable = client.patch("/api/admin/providers/meledata", json={"enabled": True})
        assert unavailable.status_code == 409  # no credentials configured
        listing = client.get("/api/admin/providers")
        assert listing.status_code == 200
        body = listing.json()
        slugs = {p["slug"]: p for p in body["providers"]}
        assert slugs["wisesub"]["enabled"] is True
        assert slugs["meledata"]["enabled"] is False
        assert body["routing"]["multi_provider_routing_enabled"] is False
        comparison = client.get("/api/admin/providers/price-comparison?network=MTN")
        assert comparison.status_code == 200
        assert comparison.json()["routing"]["primary_provider"] == "wisesub"
        bad = client.get("/api/admin/providers/price-comparison?network=Etisalat")
        assert bad.status_code == 400


def test_purchase_records_fulfillment_provider(monkeypatch):
    suffix = secrets.token_hex(4)
    with db_session() as db:
        plan_id = q(db, """INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,
            category,provider,provider_code,provider_package_code,source,provider_available)
            VALUES('MTN',:plan,485,495,1,'Monthly Plans','wisesub','mtn',:code,'wisesub',1) RETURNING id""",
            {"plan": f"Provflow {suffix}", "code": f"mtn-pf-{suffix}"}).scalar()
    plan_name = f"Provflow {suffix}"
    try:
        async def accepted(payload):
            return FakeResponse(200, {"success": True, "data": {"reference": "WS-" + suffix, "status": "successful"}})
        monkeypatch.setattr(main, "wise_purchase", accepted)
        from app.security import password_hash
        with TestClient(main.app) as client:
            client.post("/api/register", json={"name": "Prov Buyer", "email": f"provbuyer-{suffix}@example.com",
                "phone": f"081{int(suffix,16)%10**8:08d}", "password": "password123"})
            with db_session() as db:
                q(db, "UPDATE users SET balance=5000, purchase_pin=:pin WHERE email=:e",
                  {"e": f"provbuyer-{suffix}@example.com", "pin": password_hash("1234")})
            response = client.post("/api/purchase-data", json={
                "network": "MTN", "plan": plan_name, "phone": "08031234567",
                "pin": "1234", "expectedPrice": 495, "requestId": f"pf-{suffix}"})
            assert response.status_code == 200, response.text
            with db_session() as db:
                row = q(db, "SELECT provider,status FROM transactions WHERE idempotency_key=:k",
                        {"k": f"pf-{suffix}"}).mappings().first()
                assert row["provider"] == "wisesub"
                assert row["status"] == "successful"
    finally:
        with db_session() as db:
            q(db, "DELETE FROM data_plans WHERE id=:id", {"id": plan_id})


# --------------------------------------------------------------------------
# Migration/schema compatibility
# --------------------------------------------------------------------------

def test_schema_check_table_maps_are_consistent():
    """Every expected table must have entries in every per-table map.

    The PostgreSQL inspection path indexes EXPECTED_NOT_NULL[<table>]
    directly; a table listed in EXPECTED_COLUMNS but missing from the
    other maps crashed production startup while the tolerant SQLite
    path passed CI. This guard keeps the two paths equivalent.
    """
    from app.schema_check import (EXPECTED_COLUMNS, EXPECTED_CONSTRAINTS,
                                  EXPECTED_NOT_NULL, GENERATED_ID_COLUMNS)
    for table in EXPECTED_COLUMNS:
        assert table in EXPECTED_CONSTRAINTS, f"{table} missing from EXPECTED_CONSTRAINTS"
        assert table in EXPECTED_NOT_NULL, f"{table} missing from EXPECTED_NOT_NULL"
        assert table in GENERATED_ID_COLUMNS or "id" not in EXPECTED_COLUMNS[table], (
            f"{table} has an id column but no generated-id policy")


def test_schema_check_accepts_provider_tables():
    from app.schema_check import inspect_schema, schema_incompatibilities
    incompatible = schema_incompatibilities(inspect_schema())
    assert incompatible == {}, incompatible
