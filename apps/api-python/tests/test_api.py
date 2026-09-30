import os
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(__file__).parent / "test.db")
os.environ["NODE_ENV"] = "test"
os.environ["SESSION_SECRET"] = "test-session-secret-for-python-api"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_status_and_frontend():
    assert client.get("/api/status").json()["success"] is True
    assert client.get("/index.html").status_code == 200


def test_register_session_logout():
    response = client.post("/api/register", json={"name": "Test User", "email": "python-test@example.com", "phone": "08012345678", "password": "password123"})
    assert response.status_code == 200
    assert client.get("/api/session").json()["loggedIn"] is True
    assert client.post("/api/logout").status_code == 200


def test_webhook_requires_signature():
    assert client.post("/api/paystack/webhook", content=b"{}").status_code == 401
