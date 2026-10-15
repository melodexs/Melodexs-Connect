import pytest

from app import providers
from app.config import settings


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"messageId": "mocked"}


class FakeClient:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.instances.append(self)
    calls = []
    instances = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


@pytest.mark.asyncio
async def test_mocked_wisesub_and_brevo_requests(monkeypatch):
    FakeClient.calls = []
    FakeClient.instances = []
    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(settings, "wisesub_api_key", "test-key")
    monkeypatch.setattr(settings, "wisesub_api_secret", "test-secret")
    response = await providers.wise_purchase({"service_type": "data", "reference": "r1"})
    assert response.json()["messageId"] == "mocked"
    assert FakeClient.calls[0][0].endswith("/purchase")
    assert "wisesub.test" in FakeClient.calls[0][0]
    assert FakeClient.instances[0].options["follow_redirects"] is False
    assert FakeClient.calls[0][1]["headers"]["X-API-Secret"] == "test-secret"

    monkeypatch.setattr(settings, "brevo_api_key", "brevo-test")
    monkeypatch.setattr(settings, "brevo_from_email", "sender@example.com")
    await providers.send_brevo("recipient@example.com", "Subject", "<p>Mock</p>")
    assert FakeClient.calls[-1][0] == "https://api.brevo.com/v3/smtp/email"
    assert FakeClient.calls[-1][1]["headers"]["api-key"] == "brevo-test"


def test_paystack_initialize_and_verify_are_mocked(monkeypatch):
    import secrets
    from fastapi.testclient import TestClient
    from app import main
    from app.database import db_session, q

    suffix = secrets.token_hex(4)
    payload = {"name": "Payment Mock", "email": f"payment-{suffix}@example.com",
               "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"}
    calls = []

    class PaystackResponse:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    async def fake_paystack(path, method="GET", payload=None):
        calls.append((path, method, payload))
        if path == "/transaction/initialize":
            return PaystackResponse({"status": True, "data": {
                "reference": payload["reference"],
                "authorization_url": "https://paystack.test/checkout",
                "access_code": "mock-access",
            }})
        reference = path.rsplit("/", 1)[-1]
        return PaystackResponse({"status": True, "data": {
            "status": "success", "currency": "NGN", "amount": 25000,
            "reference": reference,
            "metadata": {"user_id": str(user_id)},
        }})

    monkeypatch.setattr(main, "paystack", fake_paystack)
    monkeypatch.setattr(main.settings, "paystack_secret_key", "mock-paystack-secret")
    with TestClient(main.app) as client:
        assert client.post("/api/register", json=payload).status_code == 200
        user_id = client.get("/api/session").json()["user"]["id"]
        initialized = client.post("/api/fund-wallet", json={"amount": 250})
        assert initialized.status_code == 200
        reference = initialized.json()["reference"]
        verified = client.post("/api/fund-wallet/verify", json={"reference": reference})
        assert verified.status_code == 200
        assert verified.json()["balance"] == 250
        repeated = client.post("/api/fund-wallet/verify", json={"reference": reference})
        assert repeated.status_code == 200
        assert repeated.json()["balance"] == 250

    assert calls[0][0] == "/transaction/initialize"
    assert calls[0][2]["amount"] == "25000"
    assert len(calls) == 2
    with db_session() as db:
        assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()) == 250


def test_password_reset_email_route_uses_mocked_brevo(monkeypatch):
    import secrets
    from fastapi.testclient import TestClient
    from app import main
    from app.config import settings
    from app.database import db_session, q

    suffix = secrets.token_hex(4)
    payload = {"name": "Email Mock", "email": f"email-{suffix}@example.com",
               "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"}
    sent = []

    async def fake_send_brevo(to, subject, html):
        sent.append((to, subject, html))

    monkeypatch.setattr(main, "send_brevo", fake_send_brevo)
    monkeypatch.setattr(settings, "node_env", "production")
    monkeypatch.setattr(settings, "cheapdata_public_url", "https://frontend.example")
    with TestClient(main.app) as client:
        assert client.post("/api/register", json=payload).status_code == 200
        response = client.post("/api/forgot-password", json={"email": payload["email"]})
    assert response.status_code == 200
    assert sent and sent[0][0] == payload["email"]
    assert "https://frontend.example/reset-password.html?token=" in sent[0][2]
    with db_session() as db:
        hashed = q(db, "SELECT reset_token_hash FROM users WHERE email=:email", {"email": payload["email"]}).scalar()
    assert hashed and len(hashed) == 64


def test_password_reset_email_failure_is_generic_logs_safely_and_clears_token(monkeypatch, caplog):
    import secrets
    import re
    from fastapi.testclient import TestClient
    from app import main
    from app.config import settings
    from app.database import db_session, q

    suffix = secrets.token_hex(4)
    payload = {"name": "Email Failure", "email": f"email-failure-{suffix}@example.com",
               "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"}
    issued_tokens = []

    async def failed_send(to, subject, html):
        token = re.search(r"token=([^&\"]+)", html).group(1)
        issued_tokens.append(token)
        raise RuntimeError(f"mocked email failure containing reset token {token}")

    monkeypatch.setattr(main, "send_brevo", failed_send)
    monkeypatch.setattr(settings, "node_env", "production")
    monkeypatch.setattr(settings, "cheapdata_public_url", "https://frontend.example")
    with TestClient(main.app) as client:
        assert client.post("/api/register", json=payload).status_code == 200
        response = client.post("/api/forgot-password", json={"email": payload["email"]})
        unknown_response = client.post(
            "/api/forgot-password", json={"email": f"unknown-{suffix}@example.com"}
        )
    assert response.status_code == unknown_response.status_code == 200
    assert response.json() == unknown_response.json()
    assert "Password reset email delivery failed" in caplog.text
    assert issued_tokens and all(token not in caplog.text for token in issued_tokens)
    with db_session() as db:
        row = q(db, "SELECT reset_token_hash,reset_token_expires_at FROM users WHERE email=:email", {"email": payload["email"]}).mappings().first()
    assert row["reset_token_hash"] is None
    assert row["reset_token_expires_at"] is None


def test_auth_rate_limit_is_enforced():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        responses = [client.post("/api/login", json={"email": "missing@example.com", "password": "wrong"}) for _ in range(11)]
    assert responses[-1].status_code == 429
