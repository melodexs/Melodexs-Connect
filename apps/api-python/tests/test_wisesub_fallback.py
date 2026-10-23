"""WiseSub airtime fallback activation (multi-provider routing).

ISQUAREDATA stays the primary supplier. When it refuses a purchase
BEFORE any customer debit (not configured, or its supplier wallet cannot
cover the amount), an AIRTIME purchase may be retried through WiseSub.
Data purchases are never retried: WiseSub publishes no product family
label, so data package equivalence can never be confirmed automatically
(app/package_matching.py refuses to guess).

These tests pin the whole contract:
- the fallback fires only on the pre-debit SupplierPreFlightRefusal;
- every other failure (bad PIN, insufficient balance, price change,
  provider submission error) never falls back;
- routing disabled or WiseSub unconfigured/disabled blocks the fallback;
- the fallback debits once, records provider='wisesub', and mirrors the
  proven WiseSub outcome semantics (success finalizes, anything else
  stays pending-held for reconciliation).
"""
import secrets

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.database import db_session, q
from app.provider_base import BalanceResult, PurchaseOutcome, PurchaseResult
from app.provider_isquaredata import IsquareDataAdapter


def fallback_account(client):
    suffix = secrets.token_hex(4)
    payload = {"name": "Fallback User", "email": f"fallback-{suffix}@example.com",
               "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"}
    response = client.post("/api/register", json=payload)
    assert response.status_code == 200
    return response.json()["user"]["id"]


def arm_primary_isquare(monkeypatch, *, supplier_balance):
    """Make ISQUAREDATA the primary provider with a controllable wallet."""
    monkeypatch.setattr(settings, "active_catalog_source", "isquaredata")
    monkeypatch.setattr(settings, "isquaredata_username", "test-user")
    monkeypatch.setattr(settings, "isquaredata_password", "test-pass")

    async def fake_balance(self):
        return BalanceResult(supported=True, balance=supplier_balance)

    monkeypatch.setattr(IsquareDataAdapter, "account_balance", fake_balance)


def arm_wisesub(monkeypatch, *, enabled=True, outcome=PurchaseOutcome.SUCCESSFUL):
    """Configure WiseSub with a stubbed purchase response."""
    monkeypatch.setattr(settings, "multi_provider_routing_enabled", True)
    monkeypatch.setattr(settings, "wisesub_api_key", "test-key")
    monkeypatch.setattr(settings, "wisesub_api_secret", "test-secret")
    if not enabled:
        with db_session() as db:
            q(db, "UPDATE providers SET enabled=0 WHERE slug='wisesub'")
    else:
        with db_session() as db:
            q(db, "UPDATE providers SET enabled=1 WHERE slug='wisesub'")

    submitted = {}

    async def fake_submit(self, *, network, phone, amount, reference):
        submitted.update({"network": network, "phone": phone,
                          "amount": amount, "reference": reference})
        return PurchaseResult(outcome, provider_reference=f"WS-{reference}")

    from app.provider_wisesub import WiseSubAdapter
    monkeypatch.setattr(WiseSubAdapter, "submit_airtime_purchase", fake_submit)
    return submitted


def fund(client, user_id, amount=1000):
    client.post("/api/purchase-pin/set", json={"pin": "1234"})
    with db_session() as db:
        q(db, "UPDATE users SET balance=:b WHERE id=:id", {"b": amount, "id": user_id})


AIRTIME = {"network": "MTN", "phone": "08012345678", "amount": 100, "pin": "1234"}


def last_transaction(user_id):
    with db_session() as db:
        return q(db, "SELECT status,provider,amount,description FROM transactions "
                     "WHERE user_id=:id ORDER BY id DESC LIMIT 1",
                 {"id": user_id}).mappings().first()


def test_airtime_falls_back_to_wisesub_on_preflight_refusal(monkeypatch):
    arm_primary_isquare(monkeypatch, supplier_balance=0)  # ISQUARE wallet cannot cover
    submitted = arm_wisesub(monkeypatch)
    with TestClient(main.app) as client:
        user_id = fallback_account(client)
        fund(client, user_id)
        response = client.post("/api/purchase-airtime", json=AIRTIME)
        assert response.status_code == 200, response.text
        assert response.json()["success"] is True
        assert submitted["network"] == "MTN"
        assert float(submitted["amount"]) == 100
        with db_session() as db:
            balance = float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar())
        assert balance == 900
        tx = last_transaction(user_id)
        assert tx["status"] == "successful"
        assert tx["provider"] == "wisesub"
        assert "fallback" in tx["description"].lower()


def test_data_never_falls_back(monkeypatch):
    arm_primary_isquare(monkeypatch, supplier_balance=0)
    arm_wisesub(monkeypatch)
    from app.provider_wisesub import WiseSubAdapter
    calls = []
    orig = WiseSubAdapter.submit_airtime_purchase
    async def spy(self, **kwargs):
        calls.append(kwargs)
        return await orig(self, **kwargs)
    monkeypatch.setattr(WiseSubAdapter, "submit_airtime_purchase", spy)
    with db_session() as db:
        q(db, "INSERT INTO data_plans(plan_name,network,plan,provider_cost,selling_price,active,provider_available,provider_package_code,category,source) "
              "VALUES('MTN Test 1GB','MTN','MTN Test 1GB',90,100,1,1,'pkg-1','Daily','isquaredata')")
    with TestClient(main.app) as client:
        user_id = fallback_account(client)
        fund(client, user_id)
        response = client.post("/api/purchase-data", json={"network": "MTN", "phone": "08012345678", "plan": "MTN Test 1GB", "pin": "1234"})
        assert response.status_code == 503
        assert not calls
        assert last_transaction(user_id) is None
        with db_session() as db:
            balance = float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar())
        assert balance == 1000  # nothing was debited


def test_fallback_blocked_when_routing_disabled(monkeypatch):
    arm_primary_isquare(monkeypatch, supplier_balance=0)
    monkeypatch.setattr(settings, "multi_provider_routing_enabled", False)
    monkeypatch.setattr(settings, "wisesub_api_key", "test-key")
    monkeypatch.setattr(settings, "wisesub_api_secret", "test-secret")
    with TestClient(main.app) as client:
        user_id = fallback_account(client)
        fund(client, user_id)
        response = client.post("/api/purchase-airtime", json=AIRTIME)
        assert response.status_code == 503
        assert last_transaction(user_id) is None


def test_fallback_blocked_when_wisesub_disabled(monkeypatch):
    arm_primary_isquare(monkeypatch, supplier_balance=0)
    arm_wisesub(monkeypatch, enabled=False)
    with TestClient(main.app) as client:
        user_id = fallback_account(client)
        fund(client, user_id)
        response = client.post("/api/purchase-airtime", json=AIRTIME)
        assert response.status_code == 503
        assert last_transaction(user_id) is None


def test_fallback_blocked_when_wisesub_unconfigured(monkeypatch):
    arm_primary_isquare(monkeypatch, supplier_balance=0)
    monkeypatch.setattr(settings, "multi_provider_routing_enabled", True)
    monkeypatch.setattr(settings, "wisesub_api_key", None)
    monkeypatch.setattr(settings, "wisesub_api_secret", None)
    with TestClient(main.app) as client:
        user_id = fallback_account(client)
        fund(client, user_id)
        response = client.post("/api/purchase-airtime", json=AIRTIME)
        assert response.status_code == 503
        assert last_transaction(user_id) is None


def test_wrong_pin_never_falls_back(monkeypatch):
    arm_primary_isquare(monkeypatch, supplier_balance=10_000)
    arm_wisesub(monkeypatch)
    with TestClient(main.app) as client:
        user_id = fallback_account(client)
        fund(client, user_id)
        response = client.post("/api/purchase-airtime", json={**AIRTIME, "pin": "9999"})
        assert response.status_code == 401
        assert last_transaction(user_id) is None


def test_insufficient_balance_never_falls_back(monkeypatch):
    arm_primary_isquare(monkeypatch, supplier_balance=0)
    arm_wisesub(monkeypatch)
    with TestClient(main.app) as client:
        user_id = fallback_account(client)
        fund(client, user_id, amount=50)  # less than the 100 airtime
        response = client.post("/api/purchase-airtime", json=AIRTIME)
        assert response.status_code == 400
        assert last_transaction(user_id) is None


def test_fallback_uncertain_outcome_stays_pending_held(monkeypatch):
    arm_primary_isquare(monkeypatch, supplier_balance=0)
    arm_wisesub(monkeypatch, outcome=PurchaseOutcome.UNCERTAIN)
    with TestClient(main.app) as client:
        user_id = fallback_account(client)
        fund(client, user_id)
        response = client.post("/api/purchase-airtime", json=AIRTIME)
        assert response.status_code == 202
        assert response.json()["pending"] is True
        tx = last_transaction(user_id)
        assert tx["status"] == "pending"
        assert tx["provider"] == "wisesub"
        with db_session() as db:
            balance = float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar())
        assert balance == 900  # debit held pending reconciliation


def test_fallback_purchase_is_idempotent(monkeypatch):
    arm_primary_isquare(monkeypatch, supplier_balance=0)
    submitted = arm_wisesub(monkeypatch)
    with TestClient(main.app) as client:
        user_id = fallback_account(client)
        fund(client, user_id)
        request_id = "fallback-idem-" + secrets.token_hex(4)
        first = client.post("/api/purchase-airtime", json={**AIRTIME, "requestId": request_id})
        assert first.status_code == 200
        second = client.post("/api/purchase-airtime", json={**AIRTIME, "requestId": request_id})
        assert second.status_code == 200
        assert second.json()["reference"] == first.json()["reference"]
        with db_session() as db:
            count = int(q(db, "SELECT COUNT(*) FROM transactions WHERE user_id=:id", {"id": user_id}).scalar())
            balance = float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar())
        assert count == 1  # only the registration side has no rows; exactly one debit
        assert balance == 900  # debited once


def test_pending_fallback_blocks_duplicate_submission(monkeypatch):
    arm_primary_isquare(monkeypatch, supplier_balance=0)
    submitted = arm_wisesub(monkeypatch, outcome=PurchaseOutcome.PENDING)
    with TestClient(main.app) as client:
        user_id = fallback_account(client)
        fund(client, user_id)
        first = client.post("/api/purchase-airtime", json=AIRTIME)
        assert first.status_code == 202
        # Second attempt while the first is still pending is refused with
        # the pending message, NOT resubmitted to any provider.
        submitted.clear()
        second = client.post("/api/purchase-airtime", json=AIRTIME)
        assert second.status_code == 202
        assert "do not" in second.json()["message"].lower()
        assert submitted == {}
