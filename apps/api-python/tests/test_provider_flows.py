"""Mocked provider-flow coverage for Paystack, WiseSub, and Brevo.

Every test in this module runs against an in-process ASGI client with the
provider HTTP boundary monkeypatched. These are MOCKED tests: they verify
the application's request construction, response handling, idempotency,
and failure semantics. They are NOT sandbox evidence. Real sandbox-provider
journeys remain blocked on owner-provided test credentials (checklist
Action 1) and are labeled separately in STAGING-TEST-EVIDENCE.md.
"""

import hashlib
import hmac
import json
import secrets

import pytest
from fastapi.testclient import TestClient

from app import admin_routes, main
from app.config import settings
from app.database import db_session, q


# ---------------------------------------------------------------- helpers

def _register_and_login(client, tag):
    suffix = secrets.token_hex(4)
    email = f"{tag}-{suffix}@example.com"
    payload = {
        "name": f"{tag} User",
        "email": email,
        "phone": f"080{int(suffix, 16) % 10**8:08d}",
        "password": "password123",
    }
    assert client.post("/api/register", json=payload).status_code == 200
    assert client.post("/api/login", json={"email": email, "password": "password123"}).status_code == 200
    user_id = client.get("/api/session").json()["user"]["id"]
    return user_id, email


def _seed_balance(user_id, balance):
    with db_session() as db:
        q(db, "UPDATE users SET balance=:balance WHERE id=:id", {"balance": balance, "id": user_id})


def _set_pin(client, pin="4821"):
    assert client.post("/api/purchase-pin/set", json={"pin": pin}).status_code == 200


class _PaystackResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def _success_verify_data(reference, user_id, amount_kobo, currency="NGN"):
    return {
        "status": True,
        "data": {
            "status": "success",
            "currency": currency,
            "amount": amount_kobo,
            "reference": reference,
            "metadata": {"user_id": str(user_id)},
        },
    }


# ------------------------------------------------------------- Paystack

@pytest.mark.parametrize("bad_amount", [99, 500001, 250.5, 0, -100])
def test_paystack_init_rejects_out_of_range_amounts(monkeypatch, bad_amount):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "psrange")
        monkeypatch.setattr(main.settings, "paystack_secret_key", "mock-secret")
        response = client.post("/api/fund-wallet", json={"amount": bad_amount})
        assert response.status_code == 400
        assert "between" in response.json()["message"]


def test_paystack_init_unconfigured_is_generic_500(monkeypatch):
    with TestClient(main.app) as client:
        _register_and_login(client, "psunconf")
        monkeypatch.setattr(main.settings, "paystack_secret_key", None)
        response = client.post("/api/fund-wallet", json={"amount": 500})
        assert response.status_code == 500
        assert response.json()["message"] == "Payment system is not configured yet."
        assert "mock-secret" not in response.text


def test_paystack_init_provider_error_marks_transaction_failed(monkeypatch):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "psiniterr")
        monkeypatch.setattr(main.settings, "paystack_secret_key", "mock-secret")

        async def fake_paystack(path, method="GET", payload=None):
            return _PaystackResponse(200, {"status": False, "message": "Merchant disabled"})

        monkeypatch.setattr(main, "paystack", fake_paystack)
        response = client.post("/api/fund-wallet", json={"amount": 500})
        assert response.status_code == 400
        with db_session() as db:
            status = q(db, "SELECT status FROM transactions WHERE user_id=:id AND type='wallet_funding'", {"id": user_id}).scalar()
        assert status == "failed"


def test_paystack_init_provider_timeout_is_generic_500(monkeypatch):
    with TestClient(main.app) as client:
        _register_and_login(client, "psinittimeout")
        monkeypatch.setattr(main.settings, "paystack_secret_key", "mock-secret")

        async def fake_paystack(path, method="GET", payload=None):
            raise TimeoutError("connect timeout")

        monkeypatch.setattr(main, "paystack", fake_paystack)
        response = client.post("/api/fund-wallet", json={"amount": 500})
        assert response.status_code == 500
        assert response.json()["message"] == "Unable to confirm payment initialization right now. Please try again later."


def test_paystack_verify_credits_once_then_reports_already_credited(monkeypatch):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "psverify")
        calls = []

        async def fake_paystack(path, method="GET", payload=None):
            calls.append(path)
            if path == "/transaction/initialize":
                return _PaystackResponse(200, {"status": True, "data": {"reference": payload["reference"], "authorization_url": "https://checkout.test/x", "access_code": "a"}})
            return _PaystackResponse(200, _success_verify_data(path.rsplit("/", 1)[-1], user_id, 25000))

        monkeypatch.setattr(main.settings, "paystack_secret_key", "mock-secret")
        monkeypatch.setattr(main, "paystack", fake_paystack)
        reference = client.post("/api/fund-wallet", json={"amount": 250}).json()["reference"]
        first = client.post("/api/fund-wallet/verify", json={"reference": reference})
        assert first.status_code == 200
        assert first.json()["balance"] == 250
        second = client.post("/api/fund-wallet/verify", json={"reference": reference})
        assert second.status_code == 200
        assert second.json()["message"] == "Payment has already been credited."
        assert second.json()["balance"] == 250
        # The replay short-circuits: verify was called against Paystack once.
        assert len([c for c in calls if c.startswith("/transaction/verify")]) == 1
        with db_session() as db:
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()) == 250


@pytest.mark.parametrize("tamper", ["amount", "currency", "user", "reference"])
def test_paystack_verify_rejects_tampered_payment_data(monkeypatch, tamper):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "pstamp" + tamper)
        data_cache = {}

        async def fake_paystack(path, method="GET", payload=None):
            if path == "/transaction/initialize":
                return _PaystackResponse(200, {"status": True, "data": {"reference": payload["reference"], "authorization_url": "https://checkout.test/x", "access_code": "a"}})
            reference = path.rsplit("/", 1)[-1]
            data = _success_verify_data(reference, user_id, 25000)
            if tamper == "amount":
                data["data"]["amount"] = 100
            elif tamper == "currency":
                data["data"]["currency"] = "USD"
            elif tamper == "user":
                data["data"]["metadata"] = {"user_id": str(user_id + 1)}
            elif tamper == "reference":
                data["data"]["reference"] = reference + "x"
            data_cache["data"] = data
            return _PaystackResponse(200, data)

        monkeypatch.setattr(main.settings, "paystack_secret_key", "mock-secret")
        monkeypatch.setattr(main, "paystack", fake_paystack)
        reference = client.post("/api/fund-wallet", json={"amount": 250}).json()["reference"]
        response = client.post("/api/fund-wallet/verify", json={"reference": reference})
        assert response.status_code == 400
        assert "could not be verified" in response.json()["message"]
        with db_session() as db:
            assert q(db, "SELECT status FROM transactions WHERE reference=:r", {"r": reference}).scalar() == "pending"
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()) == 0


@pytest.mark.parametrize("provider_status", ["failed", "pending", "abandoned"])
def test_paystack_verify_non_success_provider_status(monkeypatch, provider_status):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "ps" + provider_status)

        async def fake_paystack(path, method="GET", payload=None):
            if path == "/transaction/initialize":
                return _PaystackResponse(200, {"status": True, "data": {"reference": payload["reference"], "authorization_url": "https://checkout.test/x", "access_code": "a"}})
            data = _success_verify_data(path.rsplit("/", 1)[-1], user_id, 25000)
            data["data"]["status"] = provider_status
            return _PaystackResponse(200, data)

        monkeypatch.setattr(main.settings, "paystack_secret_key", "mock-secret")
        monkeypatch.setattr(main, "paystack", fake_paystack)
        reference = client.post("/api/fund-wallet", json={"amount": 250}).json()["reference"]
        response = client.post("/api/fund-wallet/verify", json={"reference": reference})
        assert response.status_code == 400
        with db_session() as db:
            assert q(db, "SELECT status FROM transactions WHERE reference=:r", {"r": reference}).scalar() == "pending"


def test_paystack_webhook_signature_enforced_and_replay_idempotent(monkeypatch):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "pswebhook")
        secret = "mock-webhook-secret"
        monkeypatch.setattr(main.settings, "paystack_secret_key", secret)
        with db_session() as db:
            q(db, "INSERT INTO transactions(user_id,type,amount,status,reference,description) VALUES(:id,'wallet_funding',250,'pending','CD-WEB-1','Paystack wallet funding')", {"id": user_id})

        event = {
            "event": "charge.success",
            "data": {
                "status": "success",
                "currency": "NGN",
                "amount": 25000,
                "reference": "CD-WEB-1",
                "metadata": {"user_id": str(user_id)},
            },
        }
        raw = json.dumps(event).encode()
        signature = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()

        # Unsigned and wrong signatures are rejected without state change.
        assert client.post("/api/paystack/webhook", content=raw, headers={"Content-Type": "application/json"}).status_code == 401
        assert client.post("/api/paystack/webhook", content=raw, headers={"Content-Type": "application/json", "x-paystack-signature": "bad"}).status_code == 401

        # Valid signature credits the wallet exactly once.
        first = client.post("/api/paystack/webhook", content=raw, headers={"Content-Type": "application/json", "x-paystack-signature": signature})
        assert first.status_code == 200
        assert first.text == "Webhook processed"
        with db_session() as db:
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()) == 250

        # Duplicate webhook delivery is idempotent: no double credit.
        replay = client.post("/api/paystack/webhook", content=raw, headers={"Content-Type": "application/json", "x-paystack-signature": signature})
        assert replay.status_code == 200
        assert replay.text == "Already processed"
        with db_session() as db:
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()) == 250
            assert q(db, "SELECT status FROM transactions WHERE reference='CD-WEB-1'").scalar() == "successful"


def test_paystack_webhook_ignores_other_events_and_invalid_json(monkeypatch):
    with TestClient(main.app) as client:
        _register_and_login(client, "pswebhookmisc")
        secret = "mock-webhook-secret"
        monkeypatch.setattr(main.settings, "paystack_secret_key", secret)

        other = json.dumps({"event": "transfer.success", "data": {}}).encode()
        signature = hmac.new(secret.encode(), other, hashlib.sha512).hexdigest()
        response = client.post("/api/paystack/webhook", content=other, headers={"Content-Type": "application/json", "x-paystack-signature": signature})
        assert response.status_code == 200
        assert response.text == "Event received"

        broken = b"{not json"
        signature = hmac.new(secret.encode(), broken, hashlib.sha512).hexdigest()
        assert client.post("/api/paystack/webhook", content=broken, headers={"Content-Type": "application/json", "x-paystack-signature": signature}).status_code == 400


# -------------------------------------------------------------- WiseSub

def _airtime_body(amount=100, pin="4821", **overrides):
    body = {"network": "MTN", "phone": "08123456789", "pin": pin, "amount": amount}
    body.update(overrides)
    return body


def test_wisesub_purchase_success_completes_transaction(monkeypatch):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "wsok")
        _set_pin(client)
        _seed_balance(user_id, 500)

        async def fake_wise_purchase(payload):
            return _PaystackResponse(200, {"success": True, "data": {"reference": "WS-OK-1"}})

        monkeypatch.setattr(main, "wise_purchase", fake_wise_purchase)
        response = client.post("/api/purchase-airtime", json=_airtime_body())
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["providerReference"] == "WS-OK-1"
        assert response.json()["balance"] == 400
        with db_session() as db:
            row = q(db, "SELECT status,provider_reference FROM transactions WHERE user_id=:id AND type='debit'", {"id": user_id}).mappings().first()
            assert row["status"] == "successful"
            assert row["provider_reference"] == "WS-OK-1"
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()) == 400


@pytest.mark.parametrize("scenario", ["timeout", "http500", "http400", "success_false", "no_reference"])
def test_wisesub_unconfirmed_outcomes_leave_pending_do_not_retry(monkeypatch, scenario):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "ws" + scenario)
        _set_pin(client)
        _seed_balance(user_id, 500)

        async def fake_wise_purchase(payload):
            if scenario == "timeout":
                raise TimeoutError("connect timeout")
            if scenario == "http500":
                return _PaystackResponse(502, {})
            if scenario == "http400":
                return _PaystackResponse(400, {"success": True})
            if scenario == "success_false":
                return _PaystackResponse(200, {"success": False})
            return _PaystackResponse(200, {"success": True, "data": {}})

        monkeypatch.setattr(main, "wise_purchase", fake_wise_purchase)
        response = client.post("/api/purchase-airtime", json=_airtime_body())
        assert response.status_code == 202
        body = response.json()
        assert body["pending"] is True
        # Every unconfirmed outcome keeps the transaction pending and tells the
        # user not to retry it manually; the wallet debit stays held.
        assert "retry" not in body["message"].lower().replace("do not retry", "")
        if scenario == "no_reference":
            assert "could not yet be fully confirmed" in body["message"]
        else:
            assert "do not retry" in body["message"].lower() or "do not submit" in body["message"].lower()
        with db_session() as db:
            row = q(db, "SELECT status,description FROM transactions WHERE user_id=:id AND type='debit'", {"id": user_id}).mappings().first()
            assert row["status"] == "pending"
            assert "WiseSub" in row["description"]
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()) == 400


def test_wisesub_duplicate_pending_purchase_is_blocked(monkeypatch):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "wsdup")
        _set_pin(client)
        _seed_balance(user_id, 1000)

        async def hanging_purchase(payload):
            raise TimeoutError("connect timeout")

        monkeypatch.setattr(main, "wise_purchase", hanging_purchase)
        first = client.post("/api/purchase-airtime", json=_airtime_body())
        assert first.status_code == 202
        # A second identical submission while the first is pending is blocked.
        second = client.post("/api/purchase-airtime", json=_airtime_body())
        assert second.status_code == 202
        assert "A matching purchase is still being confirmed" in second.json()["message"]
        with db_session() as db:
            count = q(db, "SELECT COUNT(*) FROM transactions WHERE user_id=:id AND type='debit'", {"id": user_id}).scalar()
            assert count == 1
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()) == 900


def test_wisesub_request_id_idempotency(monkeypatch):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "wsidem")
        _set_pin(client)
        _seed_balance(user_id, 500)

        async def fake_wise_purchase(payload):
            raise TimeoutError("connect timeout")

        monkeypatch.setattr(main, "wise_purchase", fake_wise_purchase)
        first = client.post("/api/purchase-airtime", json=_airtime_body(requestId="req-fixed-1"))
        assert first.status_code == 202
        retry = client.post("/api/purchase-airtime", json=_airtime_body(requestId="req-fixed-1"))
        assert retry.status_code == 202
        assert "still being confirmed" in retry.json()["message"]
        # Only one transaction and one debit exist for the request ID.
        with db_session() as db:
            rows = q(db, "SELECT reference,status FROM transactions WHERE user_id=:id AND idempotency_key='req-fixed-1'", {"id": user_id}).mappings().all()
            assert len(rows) == 1
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()) == 400

        # Once the outcome is final, the same request ID reports the stored result.
        with db_session() as db:
            q(db, "UPDATE transactions SET status='successful' WHERE idempotency_key='req-fixed-1'")
        final = client.post("/api/purchase-airtime", json=_airtime_body(requestId="req-fixed-1"))
        assert final.status_code == 200
        assert final.json()["status"] == "successful"
        assert final.json()["message"] == "This purchase request was already processed."


def test_wisesub_purchase_request_validation(monkeypatch):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "wsvalid")
        _set_pin(client)
        _seed_balance(user_id, 500)

        async def fake_wise_purchase(payload):  # pragma: no cover - must not be reached
            raise AssertionError("provider must not be called for invalid requests")

        monkeypatch.setattr(main, "wise_purchase", fake_wise_purchase)
        # Missing PIN / bad PIN / bad network / bad phone.
        assert client.post("/api/purchase-airtime", json={"network": "MTN", "phone": "08123456789", "amount": 100}).status_code == 400
        assert client.post("/api/purchase-airtime", json=_airtime_body(pin="9999")).status_code == 401
        assert client.post("/api/purchase-airtime", json=_airtime_body(network="Visafone")).status_code == 400
        assert client.post("/api/purchase-airtime", json=_airtime_body(phone="12345")).status_code == 400
        assert client.post("/api/purchase-airtime", json=_airtime_body(amount=49)).status_code == 400
        assert client.post("/api/purchase-airtime", json=_airtime_body(amount=50001)).status_code == 400
        with db_session() as db:
            assert q(db, "SELECT COUNT(*) FROM transactions WHERE user_id=:id", {"id": user_id}).scalar() == 0


def test_wisesub_data_purchase_price_change_conflict(monkeypatch):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "wsprice")
        _set_pin(client)
        _seed_balance(user_id, 500)
        with db_session() as db:
            q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,provider_package_code,source,data_size,validity,category,provider_available) VALUES('MTN','1GB',10,100,1,'mtn','pkg-1','wisesub','1GB','30 days','General',1) ON CONFLICT(network,plan) DO UPDATE SET selling_price=100,active=1,provider_available=1")

        async def fake_wise_purchase(payload):  # pragma: no cover - must not be reached
            raise AssertionError("provider must not be called on price conflict")

        monkeypatch.setattr(main, "wise_purchase", fake_wise_purchase)
        response = client.post("/api/purchase-data", json={"network": "MTN", "phone": "08123456789", "pin": "4821", "plan": "1GB", "expectedPrice": 200})
        assert response.status_code == 409
        assert "price changed" in response.json()["message"]


def test_wisesub_reconciliation_flow(monkeypatch):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "wsrecon")
        _set_pin(client)
        _seed_balance(user_id, 400)
        with db_session() as db:
            q(db, "UPDATE users SET is_admin=1 WHERE id=:id", {"id": user_id})

        async def fake_wise_purchase(payload):
            raise TimeoutError("connect timeout")

        monkeypatch.setattr(main, "wise_purchase", fake_wise_purchase)
        purchase = client.post("/api/purchase-airtime", json=_airtime_body(amount=100))
        assert purchase.status_code == 202
        reference = purchase.json()["reference"]

        # Admin sees the pending purchase.
        pending = client.get("/api/admin/purchases/pending").json()["transactions"]
        assert reference in [t["reference"] for t in pending]

        async def fake_wise_status(reference):
            return _PaystackResponse(200, {"success": True, "data": {"status": "successful"}})

        monkeypatch.setattr(admin_routes, "wise_status", fake_wise_status)
        result = client.post("/api/admin/purchases/reconcile").json()["results"]
        assert result[0]["status"] == "successful"
        with db_session() as db:
            assert q(db, "SELECT status FROM transactions WHERE user_id=:id AND type='debit'", {"id": user_id}).scalar() == "successful"

        # A second reconcile run finds nothing pending.
        again = client.post("/api/admin/purchases/reconcile").json()["results"]
        assert again == []


def test_wisesub_reconciliation_unrecognized_status_stays_pending(monkeypatch):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "wsreconweird")
        _set_pin(client)
        _seed_balance(user_id, 400)
        with db_session() as db:
            q(db, "UPDATE users SET is_admin=1 WHERE id=:id", {"id": user_id})

        async def fake_wise_purchase(payload):
            raise TimeoutError("connect timeout")

        monkeypatch.setattr(main, "wise_purchase", fake_wise_purchase)
        assert client.post("/api/purchase-airtime", json=_airtime_body(amount=100)).status_code == 202

        async def weird_status(reference):
            return _PaystackResponse(200, {"success": True, "data": {"status": "weird"}})

        monkeypatch.setattr(admin_routes, "wise_status", weird_status)
        result = client.post("/api/admin/purchases/reconcile").json()["results"]
        assert result[0]["status"] == "unresolved"
        with db_session() as db:
            assert q(db, "SELECT status FROM transactions WHERE user_id=:id AND type='debit'", {"id": user_id}).scalar() == "pending"


def test_wisesub_reconciliation_failed_without_flag_needs_review(monkeypatch):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "wsreconfail")
        _set_pin(client)
        _seed_balance(user_id, 400)
        with db_session() as db:
            q(db, "UPDATE users SET is_admin=1 WHERE id=:id", {"id": user_id})

        async def fake_wise_purchase(payload):
            raise TimeoutError("connect timeout")

        monkeypatch.setattr(main, "wise_purchase", fake_wise_purchase)
        assert client.post("/api/purchase-airtime", json=_airtime_body(amount=100)).status_code == 202

        async def failed_status(reference):
            return _PaystackResponse(200, {"success": True, "data": {"status": "failed"}})

        monkeypatch.setattr(admin_routes, "wise_status", failed_status)
        monkeypatch.setattr(admin_routes.settings, "wisesub_failure_status_confirmed", False)
        result = client.post("/api/admin/purchases/reconcile").json()["results"]
        assert result[0]["status"] == "failed_needs_admin_review"
        with db_session() as db:
            assert q(db, "SELECT status FROM transactions WHERE user_id=:id AND type='debit'", {"id": user_id}).scalar() == "pending"

        # With the flag confirmed, reconcile issues the refund and closes the transaction.
        monkeypatch.setattr(admin_routes.settings, "wisesub_failure_status_confirmed", True)
        result = client.post("/api/admin/purchases/reconcile").json()["results"]
        assert result[0]["status"] == "failed"
        with db_session() as db:
            assert q(db, "SELECT status FROM transactions WHERE user_id=:id AND type='debit'", {"id": user_id}).scalar() == "failed"
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()) == 400


def test_wisesub_reconciliation_pending_status_is_reported(monkeypatch):
    with TestClient(main.app) as client:
        user_id, _ = _register_and_login(client, "wsreconpend")
        _set_pin(client)
        _seed_balance(user_id, 400)
        with db_session() as db:
            q(db, "UPDATE users SET is_admin=1 WHERE id=:id", {"id": user_id})

        async def fake_wise_purchase(payload):
            raise TimeoutError("connect timeout")

        monkeypatch.setattr(main, "wise_purchase", fake_wise_purchase)
        assert client.post("/api/purchase-airtime", json=_airtime_body(amount=100)).status_code == 202

        async def pending_status(reference):
            return _PaystackResponse(200, {"success": True, "data": {"status": "pending"}})

        monkeypatch.setattr(admin_routes, "wise_status", pending_status)
        result = client.post("/api/admin/purchases/reconcile").json()["results"]
        assert result[0]["status"] == "pending"
        with db_session() as db:
            assert q(db, "SELECT status FROM transactions WHERE user_id=:id AND type='debit'", {"id": user_id}).scalar() == "pending"


# ---------------------------------------------------------------- Brevo

def test_brevo_unknown_email_sends_nothing_and_is_generic(monkeypatch):
    with TestClient(main.app) as client:
        sent = []

        async def fake_send_brevo(to, subject, html):
            sent.append((to, subject, html))

        monkeypatch.setattr(main, "send_brevo", fake_send_brevo)
        monkeypatch.setattr(settings, "node_env", "production")
        response = client.post("/api/forgot-password", json={"email": "nonexistent-user@example.com"})
        assert response.status_code == 200
        assert response.json()["message"] == "If an account exists with that email, password reset instructions will be provided."
        assert sent == []


@pytest.mark.asyncio
async def test_brevo_sender_configuration_and_auth_payload(monkeypatch):
    from app import providers

    captured = {}

    class CapturingResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"messageId": "mocked"}

    class CapturingClient:
        def __init__(self, **options):
            self.options = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured["headers"] = kwargs.get("headers") or {}
            captured["json"] = kwargs.get("json") or {}
            return CapturingResponse()

    monkeypatch.setattr(providers.httpx, "AsyncClient", CapturingClient)
    monkeypatch.setattr(settings, "brevo_api_key", "brevo-mock-key")
    monkeypatch.setattr(settings, "brevo_from_email", "noreply@mcx.example")
    monkeypatch.setattr(settings, "brevo_from_name", "MELODEXS CONNECT")
    await providers.send_brevo("dest@example.com", "Subject", "<p>x</p>")
    assert captured["url"] == "https://api.brevo.com/v3/smtp/email"
    assert captured["headers"].get("api-key") == "brevo-mock-key"
    assert captured["json"]["sender"]["email"] == "noreply@mcx.example"
    assert captured["json"]["sender"]["name"] == "MELODEXS CONNECT"
    assert captured["json"]["to"] == [{"email": "dest@example.com"}]
    assert captured["json"]["subject"] == "Subject"
    assert captured["json"]["htmlContent"] == "<p>x</p>"


def test_brevo_reset_requests_rotate_token_and_replay_is_safe(monkeypatch):
    with TestClient(main.app) as client:
        user_id, email = _register_and_login(client, "brevoke")
        sent_tokens = []

        async def fake_send_brevo(to, subject, html):
            sent_tokens.append(html.split("token=")[1].split('"')[0])

        monkeypatch.setattr(main, "send_brevo", fake_send_brevo)
        monkeypatch.setattr(settings, "node_env", "production")
        monkeypatch.setattr(settings, "cheapdata_public_url", "https://frontend.example")

        first = client.post("/api/forgot-password", json={"email": email})
        assert first.status_code == 200
        second = client.post("/api/forgot-password", json={"email": email})
        assert second.status_code == 200
        assert len(sent_tokens) == 2
        # Each request issues a fresh single-use token; the old one is invalidated.
        assert sent_tokens[0] != sent_tokens[1]
        with db_session() as db:
            stored = q(db, "SELECT reset_token_hash FROM users WHERE id=:id", {"id": user_id}).scalar()
        assert stored == hashlib.sha256(sent_tokens[1].encode()).hexdigest()


def test_brevo_provider_timeout_is_generic(monkeypatch):
    with TestClient(main.app) as client:
        _register_and_login(client, "brevetimeout")

        _, email = _register_and_login(client, "brevetimeout")
        sent = []

        async def failing_send_brevo(to, subject, html):
            sent.append(to)
            raise TimeoutError("connect timeout")

        monkeypatch.setattr(main, "send_brevo", failing_send_brevo)
        monkeypatch.setattr(settings, "node_env", "production")
        response = client.post("/api/forgot-password", json={"email": email})
        assert sent == [email]
        # Response is identical to the success shape: no user enumeration, no error detail.
        assert response.status_code == 200
        assert response.json()["message"] == "If an account exists with that email, password reset instructions will be provided."
