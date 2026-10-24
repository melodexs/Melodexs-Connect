"""Mixed-provider catalog visibility and per-plan purchase routing.

With multi-provider routing ENABLED and both providers eligible, the
customer catalog shows plans from every eligible provider and each data
purchase is fulfilled through the provider that OWNS the plan row.
With routing disabled, the catalog stays single-source (the pre-existing
behavior) and WiseSub plan names are refused while ISQUAREDATA is primary.
"""
import secrets

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.database import db_session, q
from app.provider_base import BalanceResult, PurchaseOutcome, PurchaseResult
from app.provider_isquaredata import IsquareDataAdapter
from app.provider_wisesub import WiseSubAdapter

WISESUB_PLAN = "MCX-WS-DATA-1GB"
ISQUARE_PLAN = "MCX-ISQ-DATA-1GB"


def mixed_account(client):
    suffix = secrets.token_hex(4)
    payload = {"name": "Mixed User", "email": f"mixed-{suffix}@example.com",
               "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"}
    response = client.post("/api/register", json=payload)
    assert response.status_code == 200
    return response.json()["user"]["id"]


def seed_plans():
    with db_session() as db:
        q(db, """INSERT INTO data_plans
                 (network, plan, category, data_size, validity, provider_cost, selling_price,
                  active, provider_available, source, provider_code, provider_package_code)
                 VALUES
                 ('MTN', :ws_plan, 'Daily', '1GB', '24 hrs', 100, 102, 1, 1, 'wisesub', 'mtn', 'ws-1gb-code'),
                 ('MTN', :isq_plan, 'Daily', '1GB', '24 hrs', 100, 102, 1, 1, 'isquaredata', 'mtn', 'isq-1gb-code')""",
          {"ws_plan": WISESUB_PLAN, "isq_plan": ISQUARE_PLAN})


def arm_mixed_catalog(monkeypatch, *, routing=True, wisesub_enabled=True):
    monkeypatch.setattr(settings, "active_catalog_source", "isquaredata")
    monkeypatch.setattr(settings, "isquaredata_username", "test-user")
    monkeypatch.setattr(settings, "isquaredata_password", "test-pass")
    monkeypatch.setattr(settings, "multi_provider_routing_enabled", routing)
    monkeypatch.setattr(settings, "wisesub_api_key", "test-key")
    monkeypatch.setattr(settings, "wisesub_api_secret", "test-secret")

    async def fake_isquare_balance(self):
        return BalanceResult(supported=True, balance=10_000)

    monkeypatch.setattr(IsquareDataAdapter, "account_balance", fake_isquare_balance)

    isquare_adapter = main.get_adapter("isquaredata")
    isquare_calls = []

    async def fake_isquare_submit(*, network, package_code, phone, reference):
        isquare_calls.append({"network": network, "package_code": package_code,
                              "phone": phone, "reference": reference})
        return PurchaseResult(outcome=PurchaseOutcome.PENDING, message="accepted")

    monkeypatch.setattr(isquare_adapter, "submit_data_purchase", fake_isquare_submit)

    submitted = {}

    class _FakeWiseResponse:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self._body = body

        def json(self):
            return self._body

    async def fake_wise_purchase(payload):
        submitted.update(payload)
        return _FakeWiseResponse(200, {"success": True, "data": {"reference": "WS-" + secrets.token_hex(4)}})

    monkeypatch.setattr(main, "wise_purchase", fake_wise_purchase)

    with db_session() as db:
        q(db, "UPDATE providers SET enabled=1 WHERE slug='isquaredata'")
        q(db, f"UPDATE providers SET enabled={1 if wisesub_enabled else 0} WHERE slug='wisesub'")
    return {"wisesub": submitted, "isquaredata": isquare_calls}


@pytest.fixture(autouse=True)
def _cleanup_mixed_rows():
    with db_session() as db:
        before = {r["slug"]: r["enabled"] for r in q(db, "SELECT slug, enabled FROM providers WHERE slug IN ('wisesub','isquaredata')").mappings()}
    yield
    with db_session() as db:
        q(db, "DELETE FROM data_plans WHERE plan IN (:a, :b)", {"a": WISESUB_PLAN, "b": ISQUARE_PLAN})
        q(db, "DELETE FROM transactions WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'mixed-%@example.com')")
        q(db, "DELETE FROM users WHERE email LIKE 'mixed-%@example.com'")
        # arm_mixed_catalog flips provider enablement; restore what the
        # module found so provider-platform tests see a pristine table.
        for slug, enabled in before.items():
            q(db, "UPDATE providers SET enabled=:e WHERE slug=:s", {"e": enabled, "s": slug})


def test_mixed_catalog_shows_both_providers_plans(monkeypatch):
    arm_mixed_catalog(monkeypatch)
    with TestClient(main.app) as client:
        seed_plans()
        body = client.get("/api/data-plans", params={"network": "MTN", "category": "Daily"}).json()
        plans = {p["plan"]: p for p in body["plans"]}
        assert WISESUB_PLAN in plans and ISQUARE_PLAN in plans
        assert plans[WISESUB_PLAN]["source"] == "wisesub"
        assert plans[ISQUARE_PLAN]["source"] == "isquaredata"
        # categories aggregate across providers
        cats = client.get("/api/data-categories", params={"network": "MTN"}).json()["categories"]
        assert any(c["category"] == "Daily" for c in cats)


def test_routing_disabled_keeps_single_source_catalog(monkeypatch):
    arm_mixed_catalog(monkeypatch, routing=False)
    with TestClient(main.app) as client:
        seed_plans()
        body = client.get("/api/data-plans", params={"network": "MTN", "category": "Daily"}).json()
        names = {p["plan"] for p in body["plans"]}
        assert ISQUARE_PLAN in names and WISESUB_PLAN not in names


def test_wisesub_disabled_hides_wisesub_plans(monkeypatch):
    arm_mixed_catalog(monkeypatch, wisesub_enabled=False)
    with TestClient(main.app) as client:
        seed_plans()
        body = client.get("/api/data-plans", params={"network": "MTN", "category": "Daily"}).json()
        names = {p["plan"] for p in body["plans"]}
        assert ISQUARE_PLAN in names and WISESUB_PLAN not in names


def test_wisesub_plan_purchase_routes_to_wisesub(monkeypatch):
    calls = arm_mixed_catalog(monkeypatch)
    submitted = calls["wisesub"]
    with TestClient(main.app) as client:
        seed_plans()
        user_id = mixed_account(client)
        client.post("/api/purchase-pin/set", json={"pin": "1234"})
        with db_session() as db:
            q(db, "UPDATE users SET balance=500 WHERE id=:id", {"id": user_id})
        response = client.post("/api/purchase-data", json={
            "network": "MTN", "phone": "08012345678", "plan": WISESUB_PLAN,
            "pin": "1234", "expectedPrice": 102, "requestId": secrets.token_hex(8),
        })
        assert response.status_code == 200, response.text
        assert response.json()["success"] is True
        # the WiseSub adapter (not ISQUAREDATA) fulfilled the purchase
        assert submitted.get("package_code") == "ws-1gb-code"
        with db_session() as db:
            tx = q(db, "SELECT status,provider FROM transactions WHERE user_id=:id ORDER BY id DESC LIMIT 1",
                   {"id": user_id}).mappings().first()
        assert tx["status"] == "successful"
        assert tx["provider"] == "wisesub"


def test_isquare_plan_purchase_still_routes_to_isquare(monkeypatch):
    calls = arm_mixed_catalog(monkeypatch)
    with TestClient(main.app) as client:
        seed_plans()
        user_id = mixed_account(client)
        client.post("/api/purchase-pin/set", json={"pin": "1234"})
        with db_session() as db:
            q(db, "UPDATE users SET balance=500 WHERE id=:id", {"id": user_id})
        response = client.post("/api/purchase-data", json={
            "network": "MTN", "phone": "08012345678", "plan": ISQUARE_PLAN,
            "pin": "1234", "expectedPrice": 102, "requestId": secrets.token_hex(8),
        })
        # ISQUAREDATA stays asynchronous: pending-held until the webhook/requery
        # finalizes it (the proven production behavior)
        assert response.status_code == 202, response.text
        assert response.json()["pending"] is True
        # WiseSub was never called; ISQUAREDATA received the submission
        assert calls["wisesub"] == {}
        assert calls["isquaredata"][0]["package_code"] == "isq-1gb-code"
        with db_session() as db:
            tx = q(db, "SELECT status,provider FROM transactions WHERE user_id=:id ORDER BY id DESC LIMIT 1",
                   {"id": user_id}).mappings().first()
        assert tx["status"] == "pending"
        assert tx["provider"] == "isquaredata"


def test_unknown_plan_with_routing_enabled_is_refused(monkeypatch):
    arm_mixed_catalog(monkeypatch)
    with TestClient(main.app) as client:
        seed_plans()
        user_id = mixed_account(client)
        client.post("/api/purchase-pin/set", json={"pin": "1234"})
        with db_session() as db:
            q(db, "UPDATE users SET balance=500 WHERE id=:id", {"id": user_id})
        response = client.post("/api/purchase-data", json={
            "network": "MTN", "phone": "08012345678", "plan": "Does Not Exist",
            "pin": "1234", "expectedPrice": 102,
        })
        assert response.status_code == 400
        # and no wallet movement
        with db_session() as db:
            balance = float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar())
        assert balance == 500
