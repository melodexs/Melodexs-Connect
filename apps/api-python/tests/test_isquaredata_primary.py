"""ISQUAREDATA as the active (primary) supplier - tests.

Covers the configuration-driven supplier switch, the ISQUAREDATA purchase
flow (pending-held outcomes, supplier pre-flight balance guard), the signed
webhook receiver (finalization, double-confirmed refunds, replay safety),
the ISQUAREDATA catalog sync with the 2% markup formula, and the retained
WiseSub provider. Everything runs against a scratch database with mocked
provider HTTP; no live calls.
"""
import hashlib
import hmac
import json
import math
import secrets
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import settings
from app.database import db_session, q
from app.provider_base import BalanceResult, PurchaseOutcome, PurchaseResult, StatusResult
from app.provider_isquaredata import IsquareDataAdapter, verify_webhook_signature
from app.provider_registry import primary_provider, resolve_fulfillment_provider, routing_status


@pytest.fixture(autouse=True)
def _cleanup_isquare_test_rows():
    """Keep the shared scratch DB clean for downstream admin tests.

    The WiseSub reconciliation tests assert on the admin reconcile
    endpoint over pending transactions; leftover ISQUAREDATA purchases or
    test users from this module would break them.
    """
    yield
    with db_session() as db:
        q(db, "DELETE FROM transactions WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'isquare-%@example.com')")
        q(db, "DELETE FROM users WHERE email LIKE 'isquare-%@example.com'")
        q(db, "DELETE FROM data_plans WHERE LOWER(TRIM(source))='isquaredata'")
        q(db, "DELETE FROM data_plans WHERE plan='WISE-1GB'")


def account(client):
    suffix = secrets.token_hex(4)
    payload = {"name": "Isquare User", "email": f"isquare-{suffix}@example.com", "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"}
    response = client.post("/api/register", json=payload)
    assert response.status_code == 200
    return payload, response.json()["user"]["id"]


@pytest.fixture()
def isquare_active(monkeypatch):
    monkeypatch.setattr(settings, "active_catalog_source", "isquaredata", raising=False)
    monkeypatch.setattr(settings, "isquaredata_username", "user", raising=False)
    monkeypatch.setattr(settings, "isquaredata_password", "secret", raising=False)
    monkeypatch.setattr(settings, "isquaredata_webhook_user_key", "user-key-123", raising=False)


def seed_isquare_plan(plan="ISQ-1GB", network="MTN", cost=100, sell=102, code="55"):
    with db_session() as db:
        q(db, """INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,
            provider_package_code,source,data_size,validity,category,provider_available,provider)
            VALUES(:network,:plan,:cost,:sell,1,'mtn',:code,'isquaredata','1GB','30 days','Monthly Plans',1,'isquaredata')
            ON CONFLICT(network,plan) DO UPDATE SET selling_price=:sell,active=1,provider_package_code=:code,
            source='isquaredata',category='Monthly Plans',provider_available=1,provider_cost=:cost""",
          {"network": network, "plan": plan, "cost": cost, "sell": sell, "code": code})


def seed_wisesub_plan(plan="WISE-1GB", network="MTN", cost=100, sell=102, code="mtn-1gb"):
    with db_session() as db:
        q(db, """INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,
            provider_package_code,source,data_size,validity,category,provider_available,provider)
            VALUES(:network,:plan,:cost,:sell,1,'mtn',:code,'wisesub','1GB','30 days','Monthly Plans',1,'wisesub')
            ON CONFLICT(network,plan) DO UPDATE SET selling_price=:sell,active=1,provider_package_code=:code,
            source='wisesub',category='Monthly Plans',provider_available=1,provider_cost=:cost""",
          {"network": network, "plan": plan, "cost": cost, "sell": sell, "code": code})


def set_wallet(user_id, balance, pin="1234"):
    with db_session() as db:
        q(db, "UPDATE users SET balance=:balance WHERE id=:id", {"balance": balance, "id": user_id})


# ---------------------------------------------------------------- config


def test_primary_provider_is_config_driven(monkeypatch):
    assert primary_provider() == "wisesub"
    monkeypatch.setattr(settings, "isquaredata_username", "user", raising=False)
    monkeypatch.setattr(settings, "isquaredata_password", "secret", raising=False)
    monkeypatch.setattr(settings, "active_catalog_source", "isquaredata", raising=False)
    assert primary_provider() == "isquaredata"
    status = routing_status()
    assert status["primary_provider"] == "isquaredata"
    adapter = resolve_fulfillment_provider("isquaredata")
    assert isinstance(adapter, IsquareDataAdapter)
    with pytest.raises(RuntimeError):
        resolve_fulfillment_provider("wisesub")
    monkeypatch.setattr(settings, "active_catalog_source", "nonsense", raising=False)
    assert primary_provider() == "wisesub"


# ---------------------------------------------------------------- catalog


def test_catalog_lists_only_active_source(isquare_active):
    seed_isquare_plan()
    seed_wisesub_plan()
    with TestClient(main.app) as client:
        plans = client.get("/api/data-plans", params={"network": "MTN"}).json()["plans"]
        names = [p["plan"] for p in plans]
        assert "ISQ-1GB" in names
        assert "WISE-1GB" not in names
        categories = client.get("/api/data-categories", params={"network": "MTN"}).json()["categories"]
        assert any(c["category"] == "Monthly Plans" for c in categories)


def test_catalog_defaults_to_wisesub_when_not_active():
    seed_isquare_plan()
    seed_wisesub_plan()
    with TestClient(main.app) as client:
        names = [p["plan"] for p in client.get("/api/data-plans", params={"network": "MTN"}).json()["plans"]]
        assert "WISE-1GB" in names
        assert "ISQ-1GB" not in names


# ---------------------------------------------------------------- purchase


def mock_adapter(monkeypatch, *, balance=None, outcome=PurchaseOutcome.PENDING,
                 status=None):
    adapter = main.get_adapter("isquaredata")

    async def fake_account_balance():
        if balance is None:
            return BalanceResult(supported=False, balance=None)
        return BalanceResult(supported=True, balance=Decimal(str(balance)))

    async def fake_data_purchase(*, network, package_code, phone, reference):
        return PurchaseResult(outcome=outcome, message="accepted")

    async def fake_status(reference):
        return StatusResult(recognized=status is not None, status=status)

    monkeypatch.setattr(adapter, "account_balance", fake_account_balance)
    monkeypatch.setattr(adapter, "submit_data_purchase", fake_data_purchase)
    monkeypatch.setattr(adapter, "transaction_status", fake_status)
    return adapter


def test_purchase_pends_and_debits(isquare_active, monkeypatch):
    mock_adapter(monkeypatch, balance=5000)
    seed_isquare_plan()
    with TestClient(main.app) as client:
        _, user_id = account(client)
        client.post("/api/purchase-pin/set", json={"pin": "1234"})
        set_wallet(user_id, 500)
        response = client.post("/api/purchase-data", json={"network": "MTN", "phone": "08012345678", "plan": "ISQ-1GB", "pin": "1234", "expectedPrice": 102})
        assert response.status_code == 202
        assert response.json()["pending"] is True
        with db_session() as db:
            row = q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()
            tx = q(db, "SELECT status,provider FROM transactions WHERE user_id=:id AND type='debit' ORDER BY id DESC LIMIT 1", {"id": user_id}).mappings().first()
        assert float(row) == 398
        assert tx["status"] == "pending" and tx["provider"] == "isquaredata"


def test_purchase_preflight_blocks_unfunded_supplier(isquare_active, monkeypatch):
    mock_adapter(monkeypatch, balance=1)
    seed_isquare_plan()
    with TestClient(main.app) as client:
        _, user_id = account(client)
        client.post("/api/purchase-pin/set", json={"pin": "1234"})
        set_wallet(user_id, 500)
        response = client.post("/api/purchase-data", json={"network": "MTN", "phone": "08012345678", "plan": "ISQ-1GB", "pin": "1234"})
        assert response.status_code == 503
        with db_session() as db:
            row = q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()
            count = q(db, "SELECT COUNT(*) FROM transactions WHERE user_id=:id", {"id": user_id}).scalar()
        assert float(row) == 500 and count == 0


def test_purchase_rejects_wisesub_plans(isquare_active, monkeypatch):
    mock_adapter(monkeypatch, balance=5000)
    seed_wisesub_plan()
    with TestClient(main.app) as client:
        _, user_id = account(client)
        client.post("/api/purchase-pin/set", json={"pin": "1234"})
        set_wallet(user_id, 500)
        response = client.post("/api/purchase-data", json={"network": "MTN", "phone": "08012345678", "plan": "WISE-1GB", "pin": "1234"})
        assert response.status_code == 400
        body = response.json()
        assert "That data plan is not currently available" in str(body.get("detail") or body.get("message") or body)


def test_purchase_price_validation(isquare_active, monkeypatch):
    mock_adapter(monkeypatch, balance=5000)
    seed_isquare_plan()
    with TestClient(main.app) as client:
        _, user_id = account(client)
        client.post("/api/purchase-pin/set", json={"pin": "1234"})
        set_wallet(user_id, 500)
        response = client.post("/api/purchase-data", json={"network": "MTN", "phone": "08012345678", "plan": "ISQ-1GB", "pin": "1234", "expectedPrice": 50})
        assert response.status_code == 409


# ---------------------------------------------------------------- webhook


def sign(payload: dict, key="user-key-123"):
    raw = json.dumps(payload).encode()
    return raw, hmac.new(key.encode(), raw, hashlib.sha512).hexdigest()


def make_pending_tx(user_id, reference, amount=102):
    with db_session() as db:
        q(db, "INSERT INTO transactions(user_id,type,amount,status,reference,description,provider) VALUES(:uid,'debit',:amount,'pending',:ref,:desc,'isquaredata')",
          {"uid": user_id, "amount": amount, "ref": reference, "desc": "MTN ISQ-1GB data purchase for 08012345678 | Pending ISQUAREDATA confirmation"})


def test_webhook_signature_unit():
    raw, sig = sign({"reference": "r1", "status": "success"})
    assert verify_webhook_signature(raw, sig, "user-key-123")
    assert not verify_webhook_signature(raw, sig, "wrong-key")
    assert not verify_webhook_signature(raw, "deadbeef", "user-key-123")
    assert not verify_webhook_signature(b"", sig, "user-key-123")


def test_webhook_invalid_signature(isquare_active):
    with TestClient(main.app) as client:
        raw, _ = sign({"reference": "r1", "status": "success"})
        response = client.post("/api/webhooks/isquaredata", content=raw, headers={"x-isquare-signature": "bad"})
        assert response.status_code == 401


def test_webhook_success_finalizes(isquare_active, monkeypatch):
    mock_adapter(monkeypatch, balance=5000)
    with TestClient(main.app) as client:
        _, user_id = account(client)
        reference = "isq-" + secrets.token_hex(6)
        make_pending_tx(user_id, reference)
        raw, sig = sign({"reference": reference, "status": "success"})
        response = client.post("/api/webhooks/isquaredata", content=raw, headers={"x-isquare-signature": sig})
        assert response.status_code == 200
        assert response.json()["status"] == "successful"
        with db_session() as db:
            tx = q(db, "SELECT status,provider_reference FROM transactions WHERE reference=:ref", {"ref": reference}).mappings().first()
        assert tx["status"] == "successful" and tx["provider_reference"] == reference
        # replay is a no-op
        response2 = client.post("/api/webhooks/isquaredata", content=raw, headers={"x-isquare-signature": sig})
        assert response2.json()["note"] == "already final"


def test_webhook_failed_confirmed_refunds(isquare_active, monkeypatch):
    mock_adapter(monkeypatch, balance=5000, status="failed")
    with TestClient(main.app) as client:
        _, user_id = account(client)
        reference = "isq-" + secrets.token_hex(6)
        make_pending_tx(user_id, reference)
        set_wallet(user_id, 0)
        raw, sig = sign({"reference": reference, "status": "failed"})
        response = client.post("/api/webhooks/isquaredata", content=raw, headers={"x-isquare-signature": sig})
        assert response.json()["status"] == "failed_refunded"
        with db_session() as db:
            tx = q(db, "SELECT status FROM transactions WHERE reference=:ref", {"ref": reference}).scalar()
            balance = q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()
        assert tx == "failed" and float(balance) == 102


def test_webhook_failed_unconfirmed_holds(isquare_active, monkeypatch):
    mock_adapter(monkeypatch, balance=5000, status=None)
    with TestClient(main.app) as client:
        _, user_id = account(client)
        reference = "isq-" + secrets.token_hex(6)
        make_pending_tx(user_id, reference)
        raw, sig = sign({"reference": reference, "status": "failed"})
        response = client.post("/api/webhooks/isquaredata", content=raw, headers={"x-isquare-signature": sig})
        assert response.json()["status"] == "failed_unconfirmed"
        with db_session() as db:
            tx = q(db, "SELECT status FROM transactions WHERE reference=:ref", {"ref": reference}).scalar()
        assert tx == "pending"


def test_webhook_unknown_reference_ignored(isquare_active):
    with TestClient(main.app) as client:
        raw, sig = sign({"reference": "does-not-exist", "status": "success"})
        response = client.post("/api/webhooks/isquaredata", content=raw, headers={"x-isquare-signature": sig})
        assert response.status_code == 200 and response.json()["ignored"] is True


def test_webhook_unconfigured_rejected(monkeypatch):
    monkeypatch.setattr(settings, "isquaredata_webhook_user_key", "", raising=False)
    with TestClient(main.app) as client:
        raw, sig = sign({"reference": "r1", "status": "success"})
        response = client.post("/api/webhooks/isquaredata", content=raw, headers={"x-isquare-signature": sig})
        assert response.status_code == 503


# ---------------------------------------------------------------- sync


def mock_catalog(monkeypatch, packages):
    adapter = main.get_adapter("isquaredata")

    class Pkg:
        def __init__(self, code, name, network, cost, size, validity, family=None):
            self.code, self.name, self.network = code, name, network
            self.cost, self.data_size, self.validity = cost, size, validity
            self.plan_type = family

    async def fake_fetch():
        return [Pkg(**p) for p in packages]

    monkeypatch.setattr(adapter, "fetch_catalog", fake_fetch)


@pytest.mark.asyncio
async def test_isquaredata_sync_uses_two_percent_formula(isquare_active, monkeypatch):
    from app.plan_sync import synchronize_isquaredata_plans
    mock_catalog(monkeypatch, [
        {"code": "501", "name": "1GB MONTHLY", "network": "MTN", "cost": "430.00", "size": "1GB", "validity": "30 days"},
        {"code": "502", "name": "500MB DAILY", "network": "MTN", "cost": "250.50", "size": "500MB", "validity": "1 day"},
    ])
    result = await synchronize_isquaredata_plans()
    assert result["added"] == 2 and result["success"] is True
    with db_session() as db:
        rows = q(db, "SELECT provider_package_code,provider_cost,selling_price,source,category,provider_available FROM data_plans WHERE source='isquaredata' ORDER BY provider_package_code").mappings().all()
    by_code = {r["provider_package_code"]: r for r in rows}
    assert float(by_code["501"]["selling_price"]) == math.ceil(430.00 * 1.02) == 439.0
    assert float(by_code["502"]["selling_price"]) == math.ceil(250.50 * 1.02) == 256.0
    assert by_code["501"]["category"] == "Monthly Plans"
    assert by_code["502"]["category"] == "Daily Plans"
    # re-sync updates instead of duplicating
    result2 = await synchronize_isquaredata_plans()
    assert result2["added"] == 0 and result2["updated"] == 2


@pytest.mark.asyncio
async def test_isquaredata_sync_marks_disappeared_plans(isquare_active, monkeypatch):
    from app.plan_sync import synchronize_isquaredata_plans
    mock_catalog(monkeypatch, [{"code": "501", "name": "1GB MONTHLY", "network": "MTN", "cost": "430.00", "size": "1GB", "validity": "30 days"}])
    await synchronize_isquaredata_plans()
    mock_catalog(monkeypatch, [])
    result = await synchronize_isquaredata_plans()
    assert result["unavailable"] == 1
    with db_session() as db:
        row = q(db, "SELECT provider_available FROM data_plans WHERE source='isquaredata' AND provider_package_code='501'").scalar()
    assert row == 0


@pytest.mark.asyncio
async def test_isquaredata_sync_never_touches_wisesub(isquare_active, monkeypatch):
    from app.plan_sync import synchronize_isquaredata_plans
    seed_wisesub_plan()
    with db_session() as db:
        before = q(db, "SELECT id,plan,provider_cost,selling_price,category,provider_available FROM data_plans WHERE source='wisesub'").mappings().all()
    mock_catalog(monkeypatch, [{"code": "501", "name": "1GB MONTHLY", "network": "MTN", "cost": "430.00", "size": "1GB", "validity": "30 days"}])
    await synchronize_isquaredata_plans()
    with db_session() as db:
        after = q(db, "SELECT id,plan,provider_cost,selling_price,category,provider_available FROM data_plans WHERE source='wisesub'").mappings().all()
    assert [dict(r) for r in before] == [dict(r) for r in after]


# ---------------------------------------------------------------- admin


def admin_client(client, user_id):
    with db_session() as db:
        q(db, "UPDATE users SET is_admin=1 WHERE id=:id", {"id": user_id})
    return client


def test_admin_cannot_disable_retained_or_active(isquare_active):
    with TestClient(main.app) as client:
        _, user_id = account(client)
        admin_client(client, user_id)
        response = client.patch("/api/admin/providers/wisesub", json={"enabled": False})
        assert response.status_code == 409
        response = client.patch("/api/admin/providers/isquaredata", json={"enabled": False})
        assert response.status_code == 409
        listing = client.get("/api/admin/providers").json()
        assert listing["routing"]["primary_provider"] == "isquaredata"
