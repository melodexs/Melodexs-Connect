"""Automatic requery sweep for stale pending ISQUAREDATA purchases.

ISQUAREDATA webhooks occasionally never arrive (incident 2026-10-23: a
customer waited a full day for a purchase the supplier had delivered).
The sweep rides the keep-alive ping (/api/status) and finalizes ONLY
supplier-confirmed deliveries, with the webhook's own semantics. Refunds
are never automatic: failures and unknown statuses stay pending-held for
admin reconciliation.
"""
import secrets
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.database import db_session, q
from app.provider_base import StatusResult
from app.provider_isquaredata import IsquareDataAdapter


@pytest.fixture(autouse=True)
def _arm_isquare_and_reset_sweep(monkeypatch):
    monkeypatch.setattr(settings, "isquaredata_username", "test-user")
    monkeypatch.setattr(settings, "isquaredata_password", "test-pass")
    monkeypatch.setattr(main, "_auto_requery_last_ran", 0.0)
    monkeypatch.setattr(main, "_auto_requery_running", False)
    yield
    with db_session() as db:
        q(db, "DELETE FROM transactions WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'sweep-%@example.com')")
        q(db, "DELETE FROM users WHERE email LIKE 'sweep-%@example.com'")


def _status_stub(monkeypatch, *, recognized, status=None, calls=None):
    async def fake_status(self, reference):
        if calls is not None:
            calls.append(reference)
        return StatusResult(recognized=recognized, status=status)
    monkeypatch.setattr(IsquareDataAdapter, "transaction_status", fake_status)


def _sweep_account_and_stale_tx(*, stale_minutes=30):
    suffix = secrets.token_hex(4)
    with TestClient(main.app) as client:
        response = client.post("/api/register", json={
            "name": "Sweep User", "email": f"sweep-{suffix}@example.com",
            "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"})
        user_id = response.json()["user"]["id"]
    reference = f"sweepref{secrets.token_hex(6)}"
    created = (datetime.now() - timedelta(minutes=stale_minutes)).strftime("%Y-%m-%d %H:%M:%S.%f")
    with db_session() as db:
        q(db, "INSERT INTO transactions(user_id, type, amount, status, reference, description, provider, created_at) "
              "VALUES(:uid, 'debit', 403, 'pending', :ref, :desc, 'isquaredata', :created)",
          {"uid": user_id, "ref": reference,
           "desc": f"MTN 1GB WEEKLY data purchase for 08012345678 | Pending ISQUAREDATA confirmation",
           "created": created})
    return reference


def test_sweep_finalizes_confirmed_delivery(monkeypatch):
    _status_stub(monkeypatch, recognized=True, status="successful")
    reference = _sweep_account_and_stale_tx()
    with TestClient(main.app) as client:
        response = client.get("/api/status")
        assert response.status_code == 200
    with db_session() as db:
        row = q(db, "SELECT status, provider_reference, description FROM transactions WHERE reference=:r",
                {"r": reference}).mappings().first()
    assert row["status"] == "successful"
    assert row["provider_reference"] == reference
    assert "auto requery sweep" in row["description"]


def test_sweep_ignores_fresh_pending(monkeypatch):
    calls = []
    _status_stub(monkeypatch, recognized=True, status="successful", calls=calls)
    reference = _sweep_account_and_stale_tx(stale_minutes=2)  # under the 10-minute threshold
    with TestClient(main.app) as client:
        client.get("/api/status")
    assert calls == []
    with db_session() as db:
        status = q(db, "SELECT status FROM transactions WHERE reference=:r", {"r": reference}).scalar()
    assert status == "pending"


def test_sweep_never_refunds_or_touches_failures(monkeypatch):
    _status_stub(monkeypatch, recognized=True, status="failed")
    reference = _sweep_account_and_stale_tx()
    with TestClient(main.app) as client:
        client.get("/api/status")
    with db_session() as db:
        row = q(db, "SELECT status, description FROM transactions WHERE reference=:r", {"r": reference}).mappings().first()
    assert row["status"] == "pending"
    assert "auto requery sweep" not in row["description"]


def test_sweep_rate_limited(monkeypatch):
    calls = []
    _status_stub(monkeypatch, recognized=True, status="successful", calls=calls)
    _sweep_account_and_stale_tx()
    with TestClient(main.app) as client:
        client.get("/api/status")   # first sweep runs (requery called)
        client.get("/api/status")   # second is within the min interval: skipped
    assert len(calls) == 1
