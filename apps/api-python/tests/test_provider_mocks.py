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
        pass
    calls = []

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
    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(settings, "wisesub_api_key", "test-key")
    monkeypatch.setattr(settings, "wisesub_api_secret", "test-secret")
    response = await providers.wise_purchase({"service_type": "data", "reference": "r1"})
    assert response.json()["messageId"] == "mocked"
    assert FakeClient.calls[0][0].endswith("/purchase")
    assert FakeClient.calls[0][1]["headers"]["X-API-Secret"] == "test-secret"

    monkeypatch.setattr(settings, "brevo_api_key", "brevo-test")
    monkeypatch.setattr(settings, "brevo_from_email", "sender@example.com")
    await providers.send_brevo("recipient@example.com", "Subject", "<p>Mock</p>")
    assert FakeClient.calls[-1][0] == "https://api.brevo.com/v3/smtp/email"
    assert FakeClient.calls[-1][1]["headers"]["api-key"] == "brevo-test"


def test_auth_rate_limit_is_enforced():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        responses = [client.post("/api/login", json={"email": "missing@example.com", "password": "wrong"}) for _ in range(11)]
    assert responses[-1].status_code == 429
