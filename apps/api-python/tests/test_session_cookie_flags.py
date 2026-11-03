"""The session cookie carries the whole login on browsers that accept it.

Its flags are security-relevant: HttpOnly keeps it away from scripts, Secure
stops it leaking over plain HTTP, SameSite=None is required because the static
site and the API are different sites, and the value must match the token that
cookie-less browsers use instead.
"""
import hashlib

from fastapi.testclient import TestClient

from app import main


def _phone(seed: str) -> str:
    """Unique number per test: phone has a UNIQUE constraint."""
    return "080" + str(int(hashlib.sha1(seed.encode()).hexdigest()[:7], 16) % 10**8).zfill(8)


def _signup(client, email, password="password123"):
    client.post("/api/register", json={"name": "Cookie Test", "email": email,
                                       "phone": _phone(email), "password": password})
    return client.post("/api/login", json={"email": email, "password": password})


def _cookie_header(response) -> str:
    headers = response.headers.get_list("set-cookie")
    return next(h for h in headers if h.startswith("melodexs_session="))


def test_cookie_is_http_only_and_scoped():
    with TestClient(main.app) as client:
        header = _cookie_header(_signup(client, "cookie-flags@example.com")).lower()
    assert "httponly" in header, "the session cookie must be unreadable from JavaScript"
    assert "path=/" in header
    assert "max-age=86400" in header, "a login should not live forever"


def test_production_adds_secure_and_cross_site_flags(monkeypatch):
    """In production the cookie must be Secure and SameSite=None, because the
    site and the API are different sites; in development it stays Lax so a
    plain-HTTP local run still works."""
    from app import security

    class ProductionSettings:
        session_secret = "test-secret"
        production = True

    monkeypatch.setattr(security, "settings", ProductionSettings)
    with TestClient(main.app) as client:
        header = _cookie_header(_signup(client, "cookie-prod@example.com")).lower()
    assert "secure" in header
    assert "samesite=none" in header


def test_the_token_matches_the_cookie_value():
    """Cookie-less clients reuse the same signed value, so both must agree."""
    with TestClient(main.app) as client:
        response = _signup(client, "cookie-token@example.com")
        raw = _cookie_header(response).split(";")[0]
    assert response.json()["session_token"] == raw.split("=", 1)[1]
