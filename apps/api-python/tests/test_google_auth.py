import secrets
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app import main
from app import google_auth
from app.database import db_session, q

client = TestClient(app)


def _unique_email():
    return f"gtest-{secrets.token_hex(5)}@example.com"


def _set_client_id(monkeypatch, value="test-google-client-id.apps.googleusercontent.com"):
    monkeypatch.setattr(main.settings, "google_client_id", value)


def test_google_config_disabled_without_client_id(monkeypatch):
    _set_client_id(monkeypatch, "")
    data = client.get("/api/auth/google/config").json()
    assert data["success"] is True
    assert data["enabled"] is False
    assert data["client_id"] is None


def test_google_config_enabled_with_client_id(monkeypatch):
    _set_client_id(monkeypatch)
    data = client.get("/api/auth/google/config").json()
    assert data["enabled"] is True
    assert data["client_id"] == "test-google-client-id.apps.googleusercontent.com"


def test_google_sign_in_creates_new_user_without_phone(monkeypatch):
    _set_client_id(monkeypatch)
    email = _unique_email()
    monkeypatch.setattr(main, "verify_google_credential", lambda c: {"email": email, "name": "Google User"})

    response = client.post("/api/auth/google", json={"credential": "valid-google-credential"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["created"] is True
    assert data["user"]["email"] == email
    assert data["user"]["phone"] is None
    assert data["user"]["has_purchase_pin"] is False
    # The session cookie must work exactly like a password login.
    assert client.get("/api/session").json()["loggedIn"] is True
    assert client.get("/api/session").json()["user"]["email"] == email
    user_id = data["user"]["id"]
    assert client.post("/api/logout").status_code == 200

    # A second sign-in with the same Google account must reuse the account.
    response = client.post("/api/auth/google", json={"credential": "valid-google-credential"})
    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["user"]["id"] == user_id
    assert client.post("/api/logout").status_code == 200

    with db_session() as db:
        stored_password = q(db, "SELECT password FROM users WHERE id=:id", {"id": user_id}).scalar()
    assert stored_password and stored_password.startswith("$2b$")


def test_google_sign_in_logs_into_existing_email_account(monkeypatch):
    _set_client_id(monkeypatch)
    email = _unique_email()
    phone = f"081{secrets.token_hex(4).isdigit() and secrets.randbelow(10**8):08d}"
    # Register the classic way first (balance 0), then sign in with Google.
    register = client.post("/api/register", json={"name": "Classic User", "email": email, "phone": phone, "password": "password123"})
    assert register.status_code == 200
    client.post("/api/logout")
    monkeypatch.setattr(main, "verify_google_credential", lambda c: {"email": email, "name": "Classic User"})
    response = client.post("/api/auth/google", json={"credential": "valid-google-credential"})
    assert response.status_code == 200
    data = response.json()
    assert data["created"] is False
    assert data["user"]["id"] == register.json()["user"]["id"]
    # The account keeps the phone it registered with.
    assert data["user"]["phone"] == phone
    assert client.post("/api/logout").status_code == 200


def test_google_sign_in_rejects_failed_verification(monkeypatch):
    _set_client_id(monkeypatch)

    def rejected(credential):
        raise HTTPException(401, "Google sign-in could not be verified. Please try again.")

    monkeypatch.setattr(main, "verify_google_credential", rejected)
    response = client.post("/api/auth/google", json={"credential": "tampered"})
    assert response.status_code == 401
    assert response.json()["success"] is False
    # No session is created on rejection.
    assert client.get("/api/session").json()["loggedIn"] is False


def test_google_sign_in_requires_configuration(monkeypatch):
    # The real verifier runs: with no client ID configured it refuses
    # before any Google request, so no account or session is created.
    _set_client_id(monkeypatch, "")
    response = client.post("/api/auth/google", json={"credential": "valid-google-credential"})
    assert response.status_code == 503
    assert client.get("/api/session").json()["loggedIn"] is False


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_verify_google_credential_enforces_google_claims(monkeypatch):
    import time as _time
    now = int(_time.time())
    valid_claims = {
        "aud": "cid.apps.googleusercontent.com",
        "iss": "https://accounts.google.com",
        "exp": now + 600,
        "email": "Owner@Example.com",
        "email_verified": "true",
        "name": "Owner Example",
    }
    _set_client_id(monkeypatch, "cid.apps.googleusercontent.com")

    def fake_get(url, params=None, timeout=None):
        token = params["id_token"]
        if token == "google-down":
            raise google_auth.httpx.HTTPError("boom")
        if token == "bad-token":
            return _FakeResponse(400, {})
        return _FakeResponse(200, valid_claims)

    monkeypatch.setattr(google_auth.httpx, "get", fake_get)

    # Happy path: email is normalized to lowercase.
    claims = google_auth.verify_google_credential("good-token")
    assert claims == {"email": "owner@example.com", "name": "Owner Example"}

    # Google unreachable -> 502, never a fallback acceptance.
    with pytest.raises(HTTPException) as err:
        google_auth.verify_google_credential("google-down")
    assert err.value.status_code == 502

    # Google rejects the token -> 401.
    with pytest.raises(HTTPException) as err:
        google_auth.verify_google_credential("bad-token")
    assert err.value.status_code == 401

    # Wrong audience (token issued for a different app) -> 401.
    monkeypatch.setattr(main.settings, "google_client_id", "other-app.apps.googleusercontent.com")
    with pytest.raises(HTTPException) as err:
        google_auth.verify_google_credential("good-token")
    assert err.value.status_code == 401
    monkeypatch.setattr(main.settings, "google_client_id", "cid.apps.googleusercontent.com")

    # Unverified email -> 401.
    valid_claims["email_verified"] = "false"
    with pytest.raises(HTTPException) as err:
        google_auth.verify_google_credential("good-token")
    assert err.value.status_code == 401
    valid_claims["email_verified"] = "true"

    # Expired -> 401.
    valid_claims["exp"] = now - 1
    with pytest.raises(HTTPException) as err:
        google_auth.verify_google_credential("good-token")
    assert err.value.status_code == 401

    # Unknown issuer -> 401.
    valid_claims["exp"] = now + 600
    valid_claims["iss"] = "https://evil.example"
    with pytest.raises(HTTPException) as err:
        google_auth.verify_google_credential("good-token")
    assert err.value.status_code == 401

    # Unconfigured API refuses verification entirely.
    monkeypatch.setattr(main.settings, "google_client_id", "")
    with pytest.raises(HTTPException) as err:
        google_auth.verify_google_credential("good-token")
    assert err.value.status_code == 503
