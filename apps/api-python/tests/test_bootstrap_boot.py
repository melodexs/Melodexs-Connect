"""Single-round-trip page boot (/api/bootstrap).

Page boot used to need /api/session then /api/user/{id} - two sequential
requests, each acquiring its own database connection. The production
database (serverless Neon, suspend_timeout_seconds=0) charges a full
handshake + resume per new connection, so every extra round trip is
directly visible as slowness in the UI. /api/bootstrap returns session
state and the user profile from ONE connection.
"""
import secrets

import pytest
from fastapi.testclient import TestClient

from app import main
from app.database import db_session, q


@pytest.fixture(autouse=True)
def _cleanup_boot_users():
    yield
    with db_session() as db:
        q(db, "DELETE FROM users WHERE email LIKE 'boot-%@example.com'")


def _register(client):
    suffix = secrets.token_hex(4)
    payload = {"name": "Boot User", "email": f"boot-{suffix}@example.com",
               "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"}
    response = client.post("/api/register", json=payload)
    assert response.status_code == 200
    return payload


def test_bootstrap_reports_logged_out_without_session():
    with TestClient(main.app) as client:
        response = client.get("/api/bootstrap")
        assert response.status_code == 200
        body = response.json()
        assert body["loggedIn"] is False
        assert body["user"] is None


def test_bootstrap_returns_session_and_user_in_one_call():
    with TestClient(main.app) as client:
        _register(client)
        client.post("/api/purchase-pin/set", json={"pin": "1234"})
        response = client.get("/api/bootstrap")
        assert response.status_code == 200
        body = response.json()
        assert body["loggedIn"] is True
        assert body["user"]["id"]
        assert body["user"]["name"] == "Boot User"
        assert body["has_purchase_pin"] is True
        # never cache a per-user boot response
        assert "no-store" in response.headers.get("cache-control", "")


def test_bootstrap_matches_session_and_user_endpoints():
    with TestClient(main.app) as client:
        _register(client)
        boot = client.get("/api/bootstrap").json()
        session = client.get("/api/session").json()
        user_id = boot["user"]["id"]
        user = client.get(f"/api/user/{user_id}").json()
        assert boot["loggedIn"] == session["loggedIn"] is True
        assert boot["user"]["email"] == user["user"]["email"]
        assert float(boot["user"]["balance"]) == float(user["user"]["balance"])
