"""Favorite recipients + transaction filtering tests (scratch DB, no live calls)."""
import secrets

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.database import db_session, q


def account(client):
    suffix = secrets.token_hex(4)
    payload = {"name": "Redesign User", "email": f"redesign-{suffix}@example.com", "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"}
    response = client.post("/api/register", json=payload)
    assert response.status_code == 200
    return payload, response.json()["user"]["id"]


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with db_session() as db:
        q(db, "DELETE FROM favorite_recipients")
        q(db, "DELETE FROM transactions WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'redesign-%@example.com')")
        q(db, "DELETE FROM users WHERE email LIKE 'redesign-%@example.com'")


def test_favorite_lifecycle():
    with TestClient(main.app) as client:
        _, user_id = account(client)
        assert client.get("/api/favorites").json()["favorites"] == []
        response = client.post("/api/favorites", json={"phone": "08012345678", "network": "MTN", "label": "My line"})
        assert response.status_code == 200
        favorites = client.get("/api/favorites").json()["favorites"]
        assert len(favorites) == 1
        assert favorites[0]["phone"] == "08012345678" and favorites[0]["network"] == "MTN"
        # duplicate rejected
        assert client.post("/api/favorites", json={"phone": "08012345678", "network": "MTN"}).status_code == 409
        # invalid phone rejected
        assert client.post("/api/favorites", json={"phone": "123", "network": "MTN"}).status_code == 400
        # delete works and is scoped to the owner
        favorite_id = favorites[0]["id"]
        assert client.request("DELETE", f"/api/favorites/{favorite_id}").status_code == 200
        assert client.get("/api/favorites").json()["favorites"] == []
        assert client.request("DELETE", f"/api/favorites/{favorite_id}").status_code == 404


def test_favorites_are_private_between_users():
    with TestClient(main.app) as client:
        _, user_a = account(client)
        client.post("/api/favorites", json={"phone": "08012345678", "network": "MTN"})
        favorite_id = client.get("/api/favorites").json()["favorites"][0]["id"]
        # second user cannot delete the first user's favorite
        _, user_b = account(client)
        assert client.request("DELETE", f"/api/favorites/{favorite_id}").status_code == 404
        assert len(client.get("/api/favorites").json()["favorites"]) == 0


def test_transaction_filtering_and_pagination():
    with TestClient(main.app) as client:
        _, user_id = account(client)
        with db_session() as db:
            q(db, "INSERT INTO transactions(user_id,type,amount,status,reference,description) VALUES(:u,'credit',1000,'successful','f1','Paystack wallet funding ref f1')", {"u": user_id})
            q(db, "INSERT INTO transactions(user_id,type,amount,status,reference,description) VALUES(:u,'debit',200,'pending','f2','MTN 1GB data purchase for 08012345678')", {"u": user_id})
            q(db, "INSERT INTO transactions(user_id,type,amount,status,reference,description) VALUES(:u,'debit',300,'failed','f3','Airtel airtime purchase')", {"u": user_id})
        # unfiltered: full history, backward compatible
        body = client.get(f"/api/transactions/{user_id}").json()
        assert len(body["transactions"]) == 3 and body["total"] == 3
        # filter by status
        pending = client.get(f"/api/transactions/{user_id}", params={"status": "pending"}).json()
        assert pending["total"] == 1 and pending["transactions"][0]["reference"] == "f2"
        # filter by type + status
        failed_debits = client.get(f"/api/transactions/{user_id}", params={"type": "debit", "status": "failed"}).json()
        assert failed_debits["total"] == 1 and failed_debits["transactions"][0]["reference"] == "f3"
        # search
        search = client.get(f"/api/transactions/{user_id}", params={"q": "airtime"}).json()
        assert search["total"] == 1 and search["transactions"][0]["reference"] == "f3"
        # pagination
        page = client.get(f"/api/transactions/{user_id}", params={"limit": 2, "offset": 0}).json()
        assert len(page["transactions"]) == 2 and page["total"] == 3
        # invalid filters rejected
        assert client.get(f"/api/transactions/{user_id}", params={"status": "bogus"}).status_code == 400
        assert client.get(f"/api/transactions/{user_id}", params={"type": "bogus"}).status_code == 400


def _tiny_png_dataurl():
    """Smallest valid 1x1 PNG as a data URL."""
    import base64
    import zlib
    def chunk(tag, data):
        c = tag + data
        return len(data).to_bytes(4, "big") + c + (zlib.crc32(c) & 0xFFFFFFFF).to_bytes(4, "big")
    ihdr = chunk(b"IHDR", (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes([8, 6, 0, 0, 0]))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff\xff"))
    iend = chunk(b"IEND", b"")
    raw = b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def test_profile_image_lifecycle():
    with TestClient(main.app) as stranger:
        # unauthenticated rejected
        assert stranger.post("/api/profile-image", json={"image": _tiny_png_dataurl()}).status_code == 401
    with TestClient(main.app) as client:
        _, user_id = account(client)
        # bad format rejected without a write
        assert client.post("/api/profile-image", json={"image": "data:image/gif;base64,AAAA"}).status_code == 400
        # valid upload round-trips through /api/user/{id}
        ok = client.post("/api/profile-image", json={"image": _tiny_png_dataurl()})
        assert ok.status_code == 200 and ok.json()["success"] is True
        me = client.get(f"/api/user/{user_id}").json()["user"]
        assert me["profile_image"].startswith("data:image/png;base64,")
        # oversized payload rejected (~300KB)
        import base64 as b64
        big = "data:image/png;base64," + b64.b64encode(b"\xff" * 300_000).decode()
        assert client.post("/api/profile-image", json={"image": big}).status_code == 400
        # removal sets it back to None
        assert client.post("/api/profile-image", json={"image": None}).status_code == 200
        me = client.get(f"/api/user/{user_id}").json()["user"]
        assert me["profile_image"] is None
