import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
import pytest

# conftest.py sets DATABASE_URL to a scratch database before import.
os.environ.setdefault("NODE_ENV", "test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-python-api")

from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.database import db_session, q
from app.security import valid_paystack_signature


def account(client):
    suffix = secrets.token_hex(4)
    payload = {"name": "Audit User", "email": f"audit-{suffix}@example.com", "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"}
    response = client.post("/api/register", json=payload)
    assert response.status_code == 200
    return payload, response.json()["user"]["id"]


def test_auth_and_authenticated_access():
    with TestClient(main.app) as client:
        payload, user_id = account(client)
        assert client.get("/api/session").json()["loggedIn"] is True
        assert client.get(f"/api/user/{user_id}").json()["success"] is True
        client.post("/api/logout")
        assert client.get(f"/api/user/{user_id}").status_code == 401
        login = client.post("/api/login", json={"email": payload["email"], "password": payload["password"]})
        assert login.status_code == 200


def test_invalid_input_and_purchase_pin_flow():
    with TestClient(main.app) as client:
        _, user_id = account(client)
        assert client.post("/api/purchase-pin/set", json={"pin": "12"}).status_code == 400
        assert client.post("/api/purchase-pin/set", json={"pin": "1234"}).status_code == 200
        assert client.post("/api/purchase-pin/verify", json={"pin": "1234"}).status_code == 200
        assert client.post("/api/purchase-pin/change", json={"currentPin": "1234", "newPin": "4321"}).status_code == 200
        assert client.post("/api/purchase-pin/verify", json={"pin": "4321"}).status_code == 200


def test_password_reset_token_flow():
    with TestClient(main.app) as client:
        payload, user_id = account(client)
        token = secrets.token_hex(32)
        with db_session() as db:
            q(db, "UPDATE users SET reset_token_hash=:hash,reset_token_expires_at=:expires WHERE id=:id", {"hash": hashlib.sha256(token.encode()).hexdigest(), "expires": int(time.time() * 1000) + 60000, "id": user_id})
        response = client.post("/api/reset-password", json={"token": token, "newPassword": "newpassword123"})
        assert response.status_code == 200
        assert client.post("/api/login", json={"email": payload["email"], "password": "newpassword123"}).status_code == 200


def test_data_plans_and_insufficient_balance():
    with TestClient(main.app) as client:
        _, user_id = account(client)
        client.post("/api/purchase-pin/set", json={"pin": "1234"})
        with db_session() as db:
            q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,provider_package_code,source,data_size,validity,category,provider_available) VALUES('MTN','1GB',10,100,1,'mtn','pkg-1','wisesub','1GB','30 days','General',1) ON CONFLICT(network,plan) DO UPDATE SET selling_price=100,active=1,provider_code='mtn',provider_package_code='pkg-1',source='wisesub',category='General',provider_available=1")
        assert client.get("/api/data-plans").status_code == 200
        response = client.post("/api/purchase-data", json={"network": "MTN", "phone": "08012345678", "plan": "1GB", "pin": "1234"})
        assert response.status_code == 400
        assert response.json()["message"] == "Insufficient wallet balance"


def test_mocked_purchase_updates_transaction_and_balance(monkeypatch):
    async def fake_purchase(payload):
        class FakeResponse:
            status_code = 200
            def json(self):
                return {"success": True, "data": {"reference": "provider-ref"}}
        return FakeResponse()

    monkeypatch.setattr(main, "wise_purchase", fake_purchase)
    with TestClient(main.app) as client:
        _, user_id = account(client)
        client.post("/api/purchase-pin/set", json={"pin": "1234"})
        with db_session() as db:
            q(db, "UPDATE users SET balance=200 WHERE id=:id", {"id": user_id})
            q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,provider_package_code,source,category) VALUES('Airtel','2GB',50,100,1,'airtel','pkg-2','wisesub','General') ON CONFLICT(network,plan) DO UPDATE SET selling_price=100,active=1,provider_code='airtel',provider_package_code='pkg-2',source='wisesub',category='General'")
        response = client.post("/api/purchase-data", json={"network": "Airtel", "phone": "08012345678", "plan": "2GB", "pin": "1234"})
        assert response.status_code == 200
        with db_session() as db:
            balance = float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar())
            transaction = q(db, "SELECT status FROM transactions WHERE user_id=:id ORDER BY id DESC", {"id": user_id}).scalar()
        assert balance == 100
        assert transaction == "successful"


def test_admin_authorization_and_cors_csrf():
    with TestClient(main.app) as client:
        assert client.get("/api/admin/stats").status_code == 401
        assert client.post("/api/login", json={"email": "missing@example.com", "password": "wrong"}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.options("/api/login", headers={"Origin": "https://melodexs-connect.onrender.com"}).status_code == 204


def test_paystack_signature_and_unsigned_webhook():
    secret = "audit-paystack-secret"
    body = json.dumps({"event": "charge.success", "data": {"reference": "unknown"}}).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    assert valid_paystack_signature(secret, body, signature)
    assert not valid_paystack_signature(secret, body, "bad")
    with TestClient(main.app) as client:
        assert client.post("/api/paystack/webhook", content=body).status_code == 401


def test_paystack_credit_is_idempotent_and_rejects_failed_funding():
    with TestClient(main.app) as client:
        _, user_id = account(client)
        reference = "test-funding-" + secrets.token_hex(8)
        with db_session() as db:
            q(db, "INSERT INTO transactions(user_id,type,amount,status,reference) VALUES(:id,'wallet_funding',250,'pending',:reference)", {"id": user_id, "reference": reference})
        payment = {"status": "success", "currency": "NGN", "amount": 25000,
                   "reference": reference, "metadata": {"user_id": str(user_id)}}

        assert asyncio.run(main.credit_paystack(reference, payment)) == "Webhook processed"
        assert asyncio.run(main.credit_paystack(reference, payment)) == "Already processed"
        with db_session() as db:
            balance = float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar())
            q(db, "INSERT INTO transactions(user_id,type,amount,status,reference) VALUES(:id,'wallet_funding',100,'failed',:reference)", {"id": user_id, "reference": reference + "-failed"})
        assert balance == 250
        with pytest.raises(ValueError):
            asyncio.run(main.credit_paystack(reference + "-failed", {
                **payment, "reference": reference + "-failed", "amount": 10000,
            }))
        with db_session() as db:
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()) == 250


def test_signed_duplicate_webhook_credits_once(monkeypatch):
    secret = "mock-webhook-secret"
    monkeypatch.setattr(main.settings, "paystack_secret_key", secret)
    with TestClient(main.app) as client:
        _, user_id = account(client)
        reference = "webhook-" + secrets.token_hex(8)
        with db_session() as db:
            q(db, "INSERT INTO transactions(user_id,type,amount,status,reference) VALUES(:id,'wallet_funding',125,'pending',:reference)", {"id": user_id, "reference": reference})
        payload = {"event": "charge.success", "data": {
            "status": "success", "currency": "NGN", "amount": 12500,
            "reference": reference, "metadata": {"user_id": str(user_id)},
        }}
        raw = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()
        headers = {"x-paystack-signature": signature}
        first = client.post("/api/paystack/webhook", content=raw, headers=headers)
        second = client.post("/api/paystack/webhook", content=raw, headers=headers)
        assert first.status_code == 200
        assert second.status_code == 200
        with db_session() as db:
            balance = float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar())
            status = q(db, "SELECT status FROM transactions WHERE reference=:reference", {"reference": reference}).scalar()
        assert balance == 125
        assert status == "successful"


def test_wisesub_error_response_stays_pending_until_outcome_is_verified(monkeypatch):
    async def rejected(payload):
        class Response:
            status_code = 400
            def json(self): return {"success": False, "message": "rejected"}
        return Response()

    monkeypatch.setattr(main, "wise_purchase", rejected)
    with TestClient(main.app) as client:
        _, user_id = account(client)
        client.post("/api/purchase-pin/set", json={"pin": "1234"})
        with db_session() as db:
            q(db, "UPDATE users SET balance=200 WHERE id=:id", {"id": user_id})
        response = client.post("/api/purchase-airtime", json={"network": "MTN", "phone": "08012345678", "amount": 50, "pin": "1234"})
        assert response.status_code == 202
        with db_session() as db:
            balance = float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar())
            status = q(db, "SELECT status FROM transactions WHERE user_id=:id ORDER BY id DESC", {"id": user_id}).scalar()
        assert balance == 150
        assert status == "pending"


def test_wisesub_timeout_keeps_debit_pending_and_blocks_retry_message(monkeypatch):
    import httpx

    async def timeout(payload):
        raise httpx.ReadTimeout("mock timeout")

    monkeypatch.setattr(main, "wise_purchase", timeout)
    with TestClient(main.app) as client:
        _, user_id = account(client)
        client.post("/api/purchase-pin/set", json={"pin": "1234"})
        with db_session() as db:
            q(db, "UPDATE users SET balance=200 WHERE id=:id", {"id": user_id})
        response = client.post("/api/purchase-airtime", json={"network": "Airtel", "phone": "08012345678", "amount": 50, "pin": "1234"})
        assert response.status_code == 202
        assert "do not retry" in response.json()["message"].lower()
        with db_session() as db:
            balance = float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar())
            status = q(db, "SELECT status FROM transactions WHERE user_id=:id ORDER BY id DESC", {"id": user_id}).scalar()
        assert balance == 150
        assert status == "pending"



def test_session_transition_from_node_connect_sid_cookie():
    """Old Express sessions never transfer; users must re-login. Logout also
    clears the old cookie name."""
    client = TestClient(main.app)
    # A request presenting only the legacy connect.sid cookie is anonymous.
    response = client.get("/api/session", cookies={"connect.sid": "legacy-express-session-value"})
    assert response.status_code == 200
    assert response.json()["loggedIn"] is False

    # Registration (which logs in) then logout: both cookie names are cleared
    # so a browser carrying the old Node cookie does not keep it.
    register = client.post("/api/register", json={
        "name": "Session Transition",
        "email": "transition-" + secrets.token_hex(4) + "@example.com",
        "phone": "08123456701",
        "password": "password123",
    })
    assert register.status_code == 200
    logout = client.post("/api/logout", cookies={"connect.sid": "legacy-express-session-value"})
    assert logout.status_code == 200
    cookie_headers = "; ".join(value for name, value in logout.headers.items() if name.lower() == "set-cookie")
    assert "melodexs_session=" in cookie_headers and "connect.sid=" in cookie_headers
    assert 'melodexs_session=""' in cookie_headers and 'connect.sid=""' in cookie_headers
    assert client.get("/api/session").json()["loggedIn"] is False
