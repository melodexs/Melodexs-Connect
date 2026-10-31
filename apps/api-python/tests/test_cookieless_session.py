"""Cookie-less sessions for browsers that block third-party cookies.

onrender.com is on the public suffix list, so the static frontend and the
API are DIFFERENT sites. Safari/iOS blocks third-party cookies by default,
which silently discarded the session cookie: login "succeeded" and every
page then bounced straight back to the login screen.

Sign-in responses now also return session_token, and the API accepts it as
`Authorization: Bearer <token>` when no cookie is present. These tests pin
that contract.
"""
import secrets

import pytest
from fastapi.testclient import TestClient

from app import main
from app.database import db_session, q


@pytest.fixture(autouse=True)
def _cleanup_cookie_less_users():
    yield
    with db_session() as db:
        q(db, "DELETE FROM transactions WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'ios-%@example.com')")
        q(db, "DELETE FROM users WHERE email LIKE 'ios-%@example.com'")


def _register(client):
    suffix = secrets.token_hex(4)
    payload = {"name": "iOS User", "email": f"ios-{suffix}@example.com",
               "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"}
    response = client.post("/api/register", json=payload)
    assert response.status_code == 200
    return payload


def test_register_and_login_return_a_session_token():
    with TestClient(main.app) as client:
        _register(client)
    with TestClient(main.app) as client:
        payload = _register(client)
        login = client.post("/api/login", json={"email": payload["email"], "password": payload["password"]})
        assert login.status_code == 200
        body = login.json()
        assert body["session_token"], "login must return a session token for cookie-less browsers"


def test_bearer_token_authenticates_when_cookies_are_blocked():
    """Exactly what iOS does: the cookie is thrown away."""
    with TestClient(main.app) as client:
        _register(client)
    with TestClient(main.app) as blocked_browser:  # fresh cookie jar, like Safari
        payload = _register(blocked_browser)
        token = blocked_browser.post(
            "/api/login", json={"email": payload["email"], "password": payload["password"]}
        ).json()["session_token"]
        cookie_free = TestClient(main.app)  # no cookies at all
        boot = cookie_free.get("/api/bootstrap", headers={"Authorization": f"Bearer {token}"})
        assert boot.status_code == 200
        body = boot.json()
        assert body["loggedIn"] is True
        assert body["user"]["email"] == payload["email"]


def test_bearer_token_is_not_accepted_without_it():
    with TestClient(main.app) as client:
        body = client.get("/api/bootstrap").json()
        assert body["loggedIn"] is False
        forged = client.get("/api/bootstrap", headers={"Authorization": "Bearer not-a-real-token"})
        assert forged.json()["loggedIn"] is False


def test_logout_invalidates_the_bearer_token():
    with TestClient(main.app) as client:
        payload = _register(client)
        token = client.post(
            "/api/login", json={"email": payload["email"], "password": payload["password"]}
        ).json()["session_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/bootstrap", headers=headers).json()["loggedIn"] is True
        client.post("/api/logout", headers=headers)
        cookie_free = TestClient(main.app)
        assert cookie_free.get("/api/bootstrap", headers=headers).json()["loggedIn"] is False
