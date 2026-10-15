"""Origin-gate safety and security-header regression tests.

These lock in two invariants of the security middleware:

1. A cross-origin request that is blocked must NEVER execute route
   side effects (registrations, purchases, PIN changes). The Node
   backend's origin gate runs before its routes; the Python middleware
   must reject blocked requests before the handler runs, not after.
2. Every outgoing response — including 403 blocked responses and 429
   rate-limited responses — carries the baseline security headers,
   matching the Node backend's helmet() behaviour (including HSTS).

Production-mode behaviour is simulated by patching the shared settings
instance; the client fixture bypasses startup, so no production
validation runs and the tests stay on the disposable test database.
"""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.database import db_session, q
from app.config import settings


PROD_FRONTEND = "https://melodexs-connect.onrender.com"


@pytest.fixture()
def production_settings(monkeypatch):
    monkeypatch.setattr(settings, "node_env", "production")
    return settings


@pytest.fixture()
def client():
    return TestClient(main.app)


def _count_users(email):
    with db_session() as db:
        return q(db, "SELECT COUNT(*) FROM users WHERE email = :email", {"email": email}).scalar()


@pytest.fixture(autouse=True)
def _cleanup_test_users():
    yield
    with db_session() as db:
        q(db, "DELETE FROM sessions")
        q(db, "DELETE FROM users WHERE email LIKE 'origin-gate-%'")


def _register_payload():
    return {
        "name": "Origin Gate Check",
        "email": "origin-gate-1@example.test",
        "phone": "08123450001",
        "password": "Origin-Gate-Pass-2026!",
    }


def test_unknown_origin_rejected_without_side_effects(client, production_settings, monkeypatch):
    monkeypatch.setattr(settings, "cheapdata_public_url", "https://configured-frontend.example")
    payload = _register_payload()
    response = client.post("/api/register", json=payload, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert response.json()["success"] is False
    assert _count_users(payload["email"]) == 0


def test_blocked_request_never_reaches_handler(production_settings, monkeypatch):
    """Regression: both origin gates must run BEFORE the route handler.
    A blocked request must never invoke call_next — the Node backend
    blocks before its routes, and the Python middleware previously ran
    its strict gate after the handler, executing side effects first.
    This unit test pins the ordering even if the two gates' origin sets
    ever drift apart (today the allowlist blocks every origin the
    strict gate would, making the strict gate unreachable via HTTP)."""
    import asyncio

    from starlette.requests import Request
    from app.main import SecurityMiddleware

    monkeypatch.setattr(settings, "cheapdata_public_url", "https://configured-frontend.example")
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/register",
        "raw_path": b"/api/register",
        "headers": [(b"origin", b"https://evil.example")],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    request = Request(scope)

    async def call_next(_request):
        raise AssertionError("route handler executed for a blocked request")

    middleware = SecurityMiddleware(main.app)
    response = asyncio.run(middleware.dispatch(request, call_next))
    assert response.status_code == 403
    assert response.headers["Strict-Transport-Security"] == "max-age=15552000; includeSubDomains"


def test_configured_origin_registration_executes(client, production_settings, monkeypatch):
    monkeypatch.setattr(settings, "cheapdata_public_url", "https://configured-frontend.example")
    payload = _register_payload()
    response = client.post("/api/register", json=payload, headers={"Origin": "https://configured-frontend.example"})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert _count_users(payload["email"]) == 1


def test_production_frontend_origin_is_always_allowed(client, production_settings, monkeypatch):
    monkeypatch.setattr(settings, "cheapdata_public_url", "https://configured-frontend.example")
    payload = _register_payload()
    response = client.post("/api/register", json=payload, headers={"Origin": PROD_FRONTEND})
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_state_changing_request_without_origin_header_is_allowed(client, production_settings, monkeypatch):
    """Curl-style server-to-server calls carry no Origin header; both
    backends let them through (the Node gate is also origin-present-only)."""
    monkeypatch.setattr(settings, "cheapdata_public_url", "https://configured-frontend.example")
    payload = _register_payload()
    response = client.post("/api/register", json=payload)
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_options_preflight_returns_204(client, production_settings, monkeypatch):
    monkeypatch.setattr(settings, "cheapdata_public_url", "https://configured-frontend.example")
    response = client.options(
        "/api/login",
        headers={
            "Origin": "https://configured-frontend.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == "https://configured-frontend.example"


def test_security_headers_on_successful_response(client):
    response = client.get("/api/status")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Strict-Transport-Security"] == "max-age=15552000; includeSubDomains"


def test_security_headers_on_blocked_response(client, production_settings, monkeypatch):
    monkeypatch.setattr(settings, "cheapdata_public_url", "https://configured-frontend.example")
    response = client.post("/api/register", json=_register_payload(), headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Strict-Transport-Security"] == "max-age=15552000; includeSubDomains"


def test_security_headers_on_rate_limited_response(client, production_settings, monkeypatch):
    """A 429 rate-limit rejection must also carry the baseline headers."""
    monkeypatch.setattr(settings, "cheapdata_public_url", "https://configured-frontend.example")
    origin = {"Origin": "https://configured-frontend.example"}
    statuses = []
    for _ in range(11):  # register limit: 10 per hour
        statuses.append(client.post("/api/register", json=_register_payload(), headers=origin).status_code)
    last = client.post("/api/register", json=_register_payload(), headers=origin)
    assert last.status_code == 429
    assert last.headers["X-Content-Type-Options"] == "nosniff"
    assert last.headers["Strict-Transport-Security"] == "max-age=15552000; includeSubDomains"
