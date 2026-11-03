"""Airtime always fulfills through WiseSub (owner directive, Oct 24 2026).

ISQUAREDATA stays the primary supplier for data plans, but AIRTIME
purchases route to WiseSub ONLY - never the primary supplier. Airtime is
fully defined by network + amount, so no product-equivalence question
arises. When WiseSub is not ready (unconfigured or disabled), the
purchase is refused cleanly BEFORE any customer debit.

These tests pin the contract:
- airtime never reaches the ISQUAREDATA flow, even when ISQUAREDATA is
  perfectly healthy and could fulfill it;
- WiseSub unconfigured or disabled => clean pre-debit refusal (503),
  no wallet movement, no transaction row;
- airtime routes through WiseSub regardless of the multi-provider
  routing flag (which stays a data-side gate);
- the WiseSub flow keeps the proven outcome semantics (success
  finalizes, anything else stays pending-held; no automatic refunds).
"""
import secrets

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.database import db_session, q
from app.provider_base import BalanceResult
from app.provider_isquaredata import IsquareDataAdapter


def account(client):
    suffix = secrets.token_hex(4)
    payload = {"name": "Airtime User", "email": f"airtime-{suffix}@example.com",
               "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"}
    response = client.post("/api/register", json=payload)
    assert response.status_code == 200
    return response.json()["user"]["id"]


def arm_primary_isquare(monkeypatch, *, supplier_balance=10_000):
    """ISQUAREDATA primary and perfectly healthy - it must NEVER see airtime."""
    monkeypatch.setattr(settings, "active_catalog_source", "isquaredata")
    monkeypatch.setattr(settings, "isquaredata_username", "test-user")
    monkeypatch.setattr(settings, "isquaredata_password", "test-pass")

    isquare_calls = []

    async def fake_isquare_balance(self):
        return BalanceResult(supported=True, balance=supplier_balance)

    async def fake_isquare_airtime(self, **kwargs):
        isquare_calls.append(kwargs)
        raise AssertionError("ISQUAREDATA must never fulfill an airtime purchase")

    monkeypatch.setattr(IsquareDataAdapter, "account_balance", fake_isquare_balance)
    monkeypatch.setattr(IsquareDataAdapter, "submit_airtime_purchase", fake_isquare_airtime)
    return isquare_calls


def arm_wisesub(monkeypatch, *, enabled=True, response=None, calls=None):
    monkeypatch.setattr(settings, "wisesub_api_key", "test-key")
    monkeypatch.setattr(settings, "wisesub_api_secret", "test-secret")

    with db_session() as db:
        q(db, f"UPDATE providers SET enabled={1 if enabled else 0} WHERE slug='wisesub'")

    class _FakeResponse:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self._body = body

        def json(self):
            return self._body

    if response is None:
        response = _FakeResponse(200, {"success": True, "data": {"reference": "WS-" + secrets.token_hex(4)}})

    async def fake_wise_purchase(payload):
        if calls is not None:
            calls.append(payload)
        return response

    monkeypatch.setattr(main, "wise_purchase", fake_wise_purchase)


def fund(client, user_id, amount=1000):
    client.post("/api/purchase-pin/set", json={"pin": "1234"})
    with db_session() as db:
        q(db, "UPDATE users SET balance=:b WHERE id=:id", {"b": amount, "id": user_id})


AIRTIME = {"network": "MTN", "phone": "08012345678", "amount": 100, "pin": "1234"}


def wallet(user_id):
    with db_session() as db:
        return float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar())


def last_transaction(user_id):
    with db_session() as db:
        return q(db, "SELECT status,provider,amount FROM transactions "
                     "WHERE user_id=:id ORDER BY id DESC LIMIT 1",
                 {"id": user_id}).mappings().first()


@pytest.fixture(autouse=True)
def _restore_providers():
    with db_session() as db:
        before = {r["slug"]: r["enabled"] for r in q(db, "SELECT slug, enabled FROM providers WHERE slug='wisesub'").mappings()}
    yield
    with db_session() as db:
        q(db, "UPDATE providers SET enabled=:e WHERE slug='wisesub'", {"e": before.get("wisesub", 1)})
        q(db, "DELETE FROM transactions WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'airtime-%@example.com')")
        q(db, "DELETE FROM users WHERE email LIKE 'airtime-%@example.com'")


def test_airtime_always_fulfills_through_wisesub(monkeypatch):
    isquare_calls = arm_primary_isquare(monkeypatch)  # ISQUARE healthy, must not be used
    wisesub_calls = []
    arm_wisesub(monkeypatch, calls=wisesub_calls)
    with TestClient(main.app) as client:
        user_id = account(client)
        fund(client, user_id)
        response = client.post("/api/purchase-airtime", json=AIRTIME)
        assert response.status_code == 200, response.text
        assert response.json()["success"] is True
        # WiseSub received the purchase with the airtime payload shape
        assert wisesub_calls[0]["service_type"] == "airtime"
        assert wisesub_calls[0]["amount"] == 100
        # ISQUAREDATA never saw anything
        assert isquare_calls == []
        # wallet debited once, transaction recorded through wisesub
        assert wallet(user_id) == 900
        tx = last_transaction(user_id)
        assert tx["status"] == "successful"
        assert tx["provider"] == "wisesub"


def test_airtime_routes_to_wisesub_even_with_routing_disabled(monkeypatch):
    arm_primary_isquare(monkeypatch)
    wisesub_calls = []
    arm_wisesub(monkeypatch, calls=wisesub_calls)
    monkeypatch.setattr(settings, "multi_provider_routing_enabled", False)
    with TestClient(main.app) as client:
        user_id = account(client)
        fund(client, user_id)
        response = client.post("/api/purchase-airtime", json=AIRTIME)
        assert response.status_code == 200, response.text
        assert wisesub_calls[0]["service_type"] == "airtime"


def test_airtime_refused_cleanly_when_wisesub_disabled(monkeypatch):
    arm_primary_isquare(monkeypatch)
    wisesub_calls = []
    arm_wisesub(monkeypatch, enabled=False, calls=wisesub_calls)
    with TestClient(main.app) as client:
        user_id = account(client)
        fund(client, user_id)
        response = client.post("/api/purchase-airtime", json=AIRTIME)
        assert response.status_code == 503
        assert "wallet was not charged" in str(response.json().get("detail") or response.json().get("message"))
        assert wallet(user_id) == 1000  # untouched
        assert wisesub_calls == []


def test_airtime_refused_cleanly_when_wisesub_unconfigured(monkeypatch):
    arm_primary_isquare(monkeypatch)
    monkeypatch.setattr(settings, "wisesub_api_key", "")
    monkeypatch.setattr(settings, "wisesub_api_secret", "")
    with TestClient(main.app) as client:
        user_id = account(client)
        fund(client, user_id)
        response = client.post("/api/purchase-airtime", json=AIRTIME)
        assert response.status_code == 503
        assert wallet(user_id) == 1000


def test_airtime_unsuccessful_outcome_stays_pending_held(monkeypatch):
    arm_primary_isquare(monkeypatch)
    class _Rejected:
        status_code = 200

        def json(self):
            return {"success": False, "message": "insufficient partner wallet"}

    arm_wisesub(monkeypatch, response=_Rejected())
    with TestClient(main.app) as client:
        user_id = account(client)
        fund(client, user_id)
        response = client.post("/api/purchase-airtime", json=AIRTIME)
        assert response.status_code == 202
        assert response.json()["pending"] is True
        tx = last_transaction(user_id)
        assert tx["status"] == "pending"
        assert tx["provider"] == "wisesub"
        # debit held, not lost
        assert wallet(user_id) == 900
