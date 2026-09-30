import os
import secrets
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///" + str(Path(__file__).parent / "test.db"))
os.environ.setdefault("NODE_ENV", "test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-python-api")

from fastapi.testclient import TestClient

from app import main
from app.database import db_session, q


def test_session_expiration_and_concurrent_sessions():
    email = f"sessions-{secrets.token_hex(4)}@example.com"
    payload = {"name": "Session User", "email": email, "phone": f"080{int(email.split("-")[1].split("@")[0], 16) % 10**8:08d}", "password": "password123"}
    with TestClient(main.app) as first:
        assert first.post("/api/register", json=payload).status_code == 200
        user_id = first.get("/api/session").json()["user"]["id"]
        with TestClient(main.app) as second:
            assert second.post("/api/login", json={"email": email, "password": "password123"}).status_code == 200
            assert first.get("/api/user/" + str(user_id)).status_code == 200
            assert second.get("/api/user/" + str(user_id)).status_code == 200
            first.post("/api/logout")
            assert second.get("/api/user/" + str(user_id)).status_code == 200
        with db_session() as db:
            q(db, "UPDATE sessions SET expire=0 WHERE sess LIKE :needle", {"needle": f'%"userId": {user_id}%'} )
        assert first.get("/api/session").json()["loggedIn"] is False

