import os
import secrets
from types import SimpleNamespace
import pytest
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(__file__).parent / "test.db")
os.environ["NODE_ENV"] = "test"
os.environ["SESSION_SECRET"] = "test-session-secret-for-python-api"

from fastapi.testclient import TestClient
from app.main import app
from app.database import db_session, q

client = TestClient(app)


@pytest.mark.asyncio
async def test_application_lifespan_startup():
    async with app.router.lifespan_context(app):
        assert app.title == "MELODEXS CONNECT API"


def test_status_and_frontend():
    assert client.get("/api/status").json()["success"] is True
    assert client.get("/index.html").status_code == 200


def test_register_session_logout():
    suffix = secrets.token_hex(4)
    response = client.post("/api/register", json={"name": "Test User", "email": f"python-test-{suffix}@example.com", "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"})
    assert response.status_code == 200
    assert client.get("/api/session").json()["loggedIn"] is True
    assert client.post("/api/logout").status_code == 200


def test_registration_rate_limit_rejects_before_creating_account():
    with db_session() as db:
        q(db, "DELETE FROM api_rate_limits")
    marker = secrets.token_hex(6)
    with TestClient(app) as client:
        responses = []
        for index in range(11):
            responses.append(client.post("/api/register", json={
                "name": "Rate Limit User",
                "email": f"rate-limit-{marker}-{index}@example.com",
                "phone": f"080{(int(marker, 16) + index) % 10**8:08d}",
                "password": "password123",
            }, headers={"Origin": "https://melodexs-connect.onrender.com"}))
    assert all(response.status_code == 200 for response in responses[:10])
    assert responses[-1].status_code == 429
    assert responses[-1].headers["access-control-allow-origin"] == "https://melodexs-connect.onrender.com"
    with db_session() as db:
        assert q(db, "SELECT COUNT(*) FROM users WHERE email LIKE :pattern", {"pattern": f"rate-limit-{marker}-%@example.com"}).scalar() == 10
        q(db, "DELETE FROM api_rate_limits")


def test_postgres_startup_only_checks_schema_without_running_ddl(monkeypatch):
    from app import main
    from app import schema_check

    monkeypatch.setattr(main, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    monkeypatch.setattr(schema_check, "inspect_schema", lambda: {})
    monkeypatch.setattr(main, "init_schema", lambda: pytest.fail("PostgreSQL startup must not initialize schema"))
    monkeypatch.setattr(main, "init_rate_limit_table", lambda: pytest.fail("PostgreSQL startup must not create tables"))
    main.startup()


def test_webhook_requires_signature():
    assert client.post("/api/paystack/webhook", content=b"{}").status_code == 401
