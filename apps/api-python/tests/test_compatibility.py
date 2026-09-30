import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///" + str(Path(__file__).parent / "test.db"))
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
            q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,provider_package_code,source,data_size,validity) VALUES('MTN','1GB',10,100,1,'mtn','pkg-1','wisesub','1GB','30 days') ON CONFLICT(network,plan) DO UPDATE SET selling_price=100,active=1,provider_code='mtn',provider_package_code='pkg-1',source='wisesub'")
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
            q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,provider_package_code,source) VALUES('Airtel','2GB',50,100,1,'airtel','pkg-2','wisesub') ON CONFLICT(network,plan) DO UPDATE SET selling_price=100,active=1,provider_code='airtel',provider_package_code='pkg-2',source='wisesub'")
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

