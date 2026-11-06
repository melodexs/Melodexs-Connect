"""The custom domain (melodex.com.ng) may call the API; strangers may not.

The site moves from melodexs-connect.onrender.com to melodex.com.ng. During
and after the move BOTH addresses must work (saved links, installed apps and
people mid-session still use the old one), while every other origin stays
blocked. An origin list is a security boundary, so these tests also try
look-alike addresses an attacker might register.
"""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import settings
from app.database import db_session, q

OLD_SITE = "https://melodexs-connect.onrender.com"
NEW_SITE = "https://melodex.com.ng"
NEW_SITE_WWW = "https://www.melodex.com.ng"
API_SITE = "https://api.melodex.com.ng"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(settings, "node_env", "production")
    # The production setting may still name the old address; the new one must
    # work regardless of what CHEAPDATA_PUBLIC_URL holds.
    monkeypatch.setattr(settings, "cheapdata_public_url", OLD_SITE)
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with db_session() as db:
        q(db, "DELETE FROM sessions")
        q(db, "DELETE FROM users WHERE email LIKE 'custom-domain-%'")


def _count(email):
    with db_session() as db:
        return q(db, "SELECT COUNT(*) FROM users WHERE email = :e", {"e": email}).scalar()


def _payload(n):
    return {
        "name": "Custom Domain Check",
        "email": f"custom-domain-{n}@example.test",
        "phone": f"0812345{n:04d}",
        "password": "Custom-Domain-Pass-2026!",
    }


@pytest.mark.parametrize("origin", [OLD_SITE, NEW_SITE, NEW_SITE_WWW])
def test_known_site_addresses_can_read(client, origin):
    response = client.get("/api/status", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert response.headers["Access-Control-Allow-Credentials"] == "true"


@pytest.mark.parametrize("n,origin", [(1, OLD_SITE), (2, NEW_SITE), (3, NEW_SITE_WWW)])
def test_known_site_addresses_can_register(client, n, origin):
    payload = _payload(n)
    response = client.post("/api/register", json=payload, headers={"Origin": origin})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert _count(payload["email"]) == 1


def test_preflight_from_new_domain_is_allowed(client):
    response = client.options(
        "/api/login",
        headers={"Origin": NEW_SITE, "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == NEW_SITE


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "https://melodex.com.ng.evil.example",   # suffix trick
        "https://evil-melodex.com.ng",           # prefix trick
        "https://melodexcom.ng",                 # missing dot
        "https://sub.melodex.com.ng",            # an unlisted subdomain
        "http://melodex.com.ng",                 # plain http, not https
        "https://melodex.ng",                    # a different domain
        "null",
    ],
)
def test_lookalike_origins_are_blocked_without_side_effects(client, origin):
    payload = _payload(9)
    response = client.post("/api/register", json=payload, headers={"Origin": origin})
    assert response.status_code == 403
    assert response.json()["success"] is False
    assert _count(payload["email"]) == 0


def test_api_subdomain_is_not_a_site_origin(client):
    """api.melodex.com.ng serves the API; pages are never loaded from it, so it
    is deliberately NOT an allowed caller."""
    response = client.post("/api/register", json=_payload(8), headers={"Origin": API_SITE})
    assert response.status_code == 403
    assert _count(_payload(8)["email"]) == 0


def test_allowlist_is_exactly_the_three_known_addresses():
    assert main.KNOWN_SITE_ORIGINS == {OLD_SITE, NEW_SITE, NEW_SITE_WWW}
