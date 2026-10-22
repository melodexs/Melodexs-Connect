"""ISQUAREDATA biller services - tests.

Electricity, cable TV and education (result-checker PINs): discovery
gating (provider disabled -> 503), meter/smartcard verification, the
shared purchase core (PIN, balance, idempotency, pending-duplicate,
supplier pre-flight, pending-held outcomes) and the education
synchronous finalization. Everything runs against the scratch SQLite
database with fully mocked provider HTTP; no live calls.
"""
import secrets
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import settings
from app.database import db_session, q
from app.provider_base import BalanceResult, PurchaseOutcome, PurchaseResult
from app.provider_isquaredata import IsquareDataAdapter


ELECTRIC_SERVICES = [{"id": 19, "name": "IKEDC - Ikeja Electricity"}]
CABLE_SERVICES = [
    {"id": 1, "name": "GOTV", "plans": [
        {"id": "gotv-max", "name": "GOtv Max N4,150", "amount": Decimal("4150.00")},
        {"id": 1, "name": "GOtv Smallie N1,900", "amount": Decimal("1900.00")},
    ]},
    {"id": 3, "name": "DSTV", "plans": [
        {"id": 32, "name": "DStv Padi N4,400", "amount": Decimal("4400.00")},
    ]},
]
EDUCATION_SERVICES = [
    {"id": 11, "name": "WAEC", "api_amount": Decimal("5300.00"), "is_active": True},
    {"id": 12, "name": "NECO", "api_amount": Decimal("2150.00"), "is_active": True},
    {"id": 25, "name": "NABTEB", "api_amount": Decimal("820.00"), "is_active": False},
]


@pytest.fixture()
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def _cleanup_biller_test_rows():
    yield
    with db_session() as db:
        q(db, "DELETE FROM transactions WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'biller-%@example.com')")
        q(db, "DELETE FROM users WHERE email LIKE 'biller-%@example.com'")
        q(db, "UPDATE providers SET enabled=0 WHERE slug='isquaredata'")


def account(client):
    suffix = secrets.token_hex(4)
    payload = {"name": "Biller User", "email": f"biller-{suffix}@example.com",
                "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"}
    response = client.post("/api/register", json=payload)
    assert response.status_code == 200
    user_id = response.json()["user"]["id"]
    assert client.post("/api/purchase-pin/set", json={"pin": "1234"}).status_code == 200
    return payload["email"], user_id


def fund(user_id, amount):
    with db_session() as db:
        q(db, "UPDATE users SET balance=balance+:amount WHERE id=:id", {"amount": amount, "id": user_id})


def enable_isquare(monkeypatch):
    monkeypatch.setattr(settings, "isquaredata_username", "user", raising=False)
    monkeypatch.setattr(settings, "isquaredata_password", "secret", raising=False)
    with db_session() as db:
        q(db, "UPDATE providers SET enabled=1 WHERE slug='isquaredata'")
        row = q(db, "SELECT enabled FROM providers WHERE slug='isquaredata'").first()
        assert row and row[0] == 1


def _async_method(value):
    """Build a proper async mock method for the adapter class."""
    async def _call(self, *args, **kwargs):
        return value
    return _call


@pytest.fixture()
def isquare_enabled(monkeypatch):
    enable_isquare(monkeypatch)
    monkeypatch.setattr(IsquareDataAdapter, "account_balance",
                        _async_method(BalanceResult(supported=True, balance=Decimal("1000000"), currency="NGN")))
    monkeypatch.setattr(IsquareDataAdapter, "fetch_electricity_services",
                        _async_method(ELECTRIC_SERVICES))
    monkeypatch.setattr(IsquareDataAdapter, "fetch_cable_services",
                        _async_method(CABLE_SERVICES))
    monkeypatch.setattr(IsquareDataAdapter, "fetch_education_services",
                        _async_method(EDUCATION_SERVICES))


def _pending_purchase(*args, **kwargs):
    return PurchaseResult(outcome=PurchaseOutcome.PENDING,
                          message="ISQUAREDATA accepted the request; outcome pending reconciliation")


def set_purchase_outcome(monkeypatch, result=None):
    monkeypatch.setattr(IsquareDataAdapter, "submit_electricity_purchase", _pending_purchase)
    monkeypatch.setattr(IsquareDataAdapter, "submit_cable_purchase", _pending_purchase)
    monkeypatch.setattr(IsquareDataAdapter, "submit_education_purchase", _pending_purchase)
    if result is not None:
        monkeypatch.setattr(IsquareDataAdapter, "submit_education_purchase", result)


def login(client, email):
    response = client.post("/api/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200


def tx_status(reference):
    with db_session() as db:
        row = q(db, "SELECT status, description, amount FROM transactions WHERE reference=:ref", {"ref": reference}).mappings().first()
    return row


# ---------------------------------------------------------------------
# gating: provider disabled -> 503; unauthenticated -> 401
# ---------------------------------------------------------------------

def test_billers_unavailable_while_provider_disabled(client):
    _, user_id = account(client)
    login(client, _email_of(user_id))
    with db_session() as db:
        q(db, "UPDATE providers SET enabled=0 WHERE slug='isquaredata'")
    assert client.get("/api/billers").status_code == 200
    assert client.get("/api/billers").json()["electricity"] is False
    assert client.get("/api/billers/electricity").status_code == 503
    assert client.get("/api/billers/cable").status_code == 503
    assert client.get("/api/billers/education").status_code == 503
    assert client.post("/api/purchase-electricity", json={}).status_code == 503
    assert client.post("/api/purchase-cable", json={}).status_code == 503
    assert client.post("/api/purchase-education", json={}).status_code == 503


def _email_of(user_id):
    with db_session() as db:
        return q(db, "SELECT email FROM users WHERE id=:id", {"id": user_id}).mappings().first()["email"]


def test_billers_require_authentication(client):
    assert client.get("/api/billers/electricity").status_code == 401
    assert client.get("/api/billers/electricity/verify").status_code == 401
    assert client.get("/api/billers/cable").status_code == 401
    assert client.get("/api/billers/education").status_code == 401
    assert client.post("/api/billers/cable/verify", json={}).status_code == 401
    assert client.post("/api/purchase-electricity", json={}).status_code == 401
    assert client.post("/api/purchase-cable", json={}).status_code == 401
    assert client.post("/api/purchase-education", json={}).status_code == 401


# ---------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------

def test_biller_lists_and_prices(client, isquare_enabled):
    email, _ = account(client)
    login(client, email)
    body = client.get("/api/billers/electricity").json()
    assert body == {"services": [{"id": 19, "name": "IKEDC - Ikeja Electricity"}]}
    cable = client.get("/api/billers/cable").json()["services"]
    assert {svc["name"] for svc in cable} == {"GOTV", "DSTV"}
    assert client.get("/api/billers").json()["cable"] is True
    education = client.get("/api/billers/education").json()["services"]
    # active only, 2% markup applied to the API cost
    assert [svc["name"] for svc in education] == ["WAEC", "NECO"]
    assert education[0]["selling_price"] == 5406  # ceil(5300 * 1.02)
    assert education[1]["selling_price"] == 2193  # ceil(2150 * 1.02)


def test_meter_and_smartcard_verification(client, isquare_enabled, monkeypatch):
    email, _ = account(client)
    login(client, email)

    async def verify_meter(self, *, service_id, meter_type, meter_number):
        return ({"status": True, "customer_name": "ADIGUN SHERIF", "message": None}
                if meter_number == "1111111111111"
                else {"status": False, "customer_name": None, "message": "Invalid Meter Number"})

    async def verify_smartcard(self, *, plan_id, smartcard):
        return ({"status": True, "customer_name": "MR ADIGUN SHERIF", "message": None}
                if smartcard == "01831333090"
                else {"status": False, "customer_name": None, "message": "Invalid smartcard"})

    monkeypatch.setattr(IsquareDataAdapter, "verify_meter", verify_meter)
    monkeypatch.setattr(IsquareDataAdapter, "verify_smartcard", verify_smartcard)

    ok = client.get("/api/billers/electricity/verify",
                    params={"service_id": 19, "meter_type": "prepaid", "meter_number": "1111111111111"})
    assert ok.status_code == 200 and ok.json()["customer_name"] == "ADIGUN SHERIF"
    bad = client.get("/api/billers/electricity/verify",
                     params={"service_id": 19, "meter_type": "prepaid", "meter_number": "0000000000"})
    assert bad.status_code == 400
    assert "Invalid" in str(bad.json().get("detail") or bad.json().get("message"))

    ok = client.post("/api/billers/cable/verify", json={"plan_id": 1, "smartcard": "01831333090"})
    assert ok.status_code == 200 and ok.json()["customer_name"] == "MR ADIGUN SHERIF"
    bad_card = client.post("/api/billers/cable/verify", json={"plan_id": 1, "smartcard": "123"})
    assert bad_card.status_code == 400


# ---------------------------------------------------------------------
# electricity purchases
# ---------------------------------------------------------------------

def test_electricity_purchase_holds_pending_and_debits_wallet(client, isquare_enabled, monkeypatch):
    email, user_id = account(client)
    login(client, email)
    fund(user_id, 20000)
    set_purchase_outcome(monkeypatch)
    response = client.post("/api/purchase-electricity", json={
        "service_id": 19, "meter_type": "prepaid", "meter_number": "1111111111111",
        "phone_number": "08012345678", "customer_name": "ADIGUN SHERIF",
        "amount": 5000, "pin": "1234", "requestId": "req-elec-1",
    })
    assert response.status_code == 202
    assert response.json()["pending"] is True
    reference = response.json()["reference"]
    row = tx_status(reference)
    assert row["status"] == "pending"
    assert "IKEDC" in row["description"] and "1111111111111" in row["description"]
    with db_session() as db:
        assert q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar() == 15000
    # idempotent replay: same requestId returns the same pending reference
    replay = client.post("/api/purchase-electricity", json={
        "service_id": 19, "meter_type": "prepaid", "meter_number": "1111111111111",
        "phone_number": "08012345678", "amount": 5000, "pin": "1234", "requestId": "req-elec-1",
    })
    assert replay.status_code == 202 and replay.json()["reference"] == reference
    with db_session() as db:
        assert q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar() == 15000


def test_electricity_purchase_validation(client, isquare_enabled, monkeypatch):
    email, user_id = account(client)
    login(client, email)
    fund(user_id, 20000)
    set_purchase_outcome(monkeypatch)
    base = {"service_id": 19, "meter_type": "prepaid", "meter_number": "1111111111111",
            "phone_number": "08012345678", "pin": "1234"}
    assert client.post("/api/purchase-electricity", json={**base, "amount": 100}).status_code == 400
    assert client.post("/api/purchase-electricity", json={**base, "amount": 5000, "pin": "0000"}).status_code == 401
    assert client.post("/api/purchase-electricity", json={**base, "amount": 5000, "meter_number": "12"}).status_code == 400
    assert client.post("/api/purchase-electricity", json={**base, "amount": 200000}).status_code == 400
    assert client.post("/api/purchase-electricity", json={**base, "amount": 999, "service_id": 999}).status_code == 400
    with db_session() as db:
        assert q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar() == 20000


def test_electricity_insufficient_balance_and_preflight(client, isquare_enabled, monkeypatch):
    email, user_id = account(client)
    login(client, email)
    fund(user_id, 100)
    set_purchase_outcome(monkeypatch)
    response = client.post("/api/purchase-electricity", json={
        "service_id": 19, "meter_type": "prepaid", "meter_number": "1111111111111",
        "phone_number": "08012345678", "amount": 5000, "pin": "1234"})
    assert response.status_code == 400
    # supplier pre-flight: funded wallet but an unreachable supplier balance
    fund(user_id, 100000)
    monkeypatch.setattr(IsquareDataAdapter, "account_balance",
                        _async_method(BalanceResult(supported=True, message="unavailable")))
    response = client.post("/api/purchase-electricity", json={
        "service_id": 19, "meter_type": "prepaid", "meter_number": "1111111111111",
        "phone_number": "08012345678", "amount": 5000, "pin": "1234"})
    assert response.status_code == 503
    with db_session() as db:
        assert q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar() == 100100


# ---------------------------------------------------------------------
# cable purchases
# ---------------------------------------------------------------------

def test_cable_purchase_uses_provider_price_and_pending(client, isquare_enabled, monkeypatch):
    email, user_id = account(client)
    login(client, email)
    fund(user_id, 20000)
    captured = {}

    async def submit_cable(self, *, service_id, plan_id, smartcard, phone, amount, subscription_type, reference):
        captured.update(plan_id=plan_id, amount=amount, subscription_type=subscription_type, reference=reference)
        return PurchaseResult(outcome=PurchaseOutcome.PENDING, message="pending")

    monkeypatch.setattr(IsquareDataAdapter, "submit_cable_purchase", submit_cable)
    response = client.post("/api/purchase-cable", json={
        "service_id": 1, "plan_id": 1, "smartcard": "01831333090",
        "phone_number": "08012345678", "customer_name": "MR ADIGUN SHERIF",
        "subscription_type": "renew", "pin": "1234", "requestId": "req-cable-1",
    })
    assert response.status_code == 202
    row = tx_status(response.json()["reference"])
    assert row["status"] == "pending"
    assert row["amount"] == 1900 and "GOtv Smallie" in row["description"]
    assert captured["plan_id"] == 1 and float(captured["amount"]) == 1900.00
    # price tampering is refused against the live provider price
    response = client.post("/api/purchase-cable", json={
        "service_id": 1, "plan_id": 1, "smartcard": "01831333090",
        "phone_number": "08012345678", "subscription_type": "renew",
        "expectedPrice": 100, "pin": "1234"})
    assert response.status_code == 409


# ---------------------------------------------------------------------
# education purchases (synchronous finalization)
# ---------------------------------------------------------------------

def test_education_purchase_finalizes_with_pin(client, isquare_enabled, monkeypatch):
    email, user_id = account(client)
    login(client, email)
    fund(user_id, 10000)

    async def submit_education(self, **kwargs):
        return PurchaseResult(outcome=PurchaseOutcome.SUCCESSFUL, provider_reference=kwargs.get("reference"),
                              message="Education PIN purchase confirmed; PIN: 1234-5678, SERIAL NUMBER: A1")

    monkeypatch.setattr(IsquareDataAdapter, "submit_education_purchase", submit_education)
    response = client.post("/api/purchase-education", json={
        "service_id": 11, "quantity": 1, "phone_number": "08012345678",
        "email_address": "student@example.com", "pin": "1234", "requestId": "req-edu-1",
    })
    assert response.status_code == 200 and response.json()["status"] == "successful"
    row = tx_status(response.json()["reference"])
    assert row["status"] == "successful"
    assert "PIN: 1234-5678" in row["description"] and "WAEC" in row["description"]
    assert row["amount"] == 5406  # ceil(5300 * 1.02) x 1
    with db_session() as db:
        assert q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar() == 10000 - 5406


def test_education_purchase_failed_stays_pending(client, isquare_enabled, monkeypatch):
    email, user_id = account(client)
    login(client, email)
    fund(user_id, 10000)

    async def submit_education(self, **kwargs):
        return PurchaseResult(outcome=PurchaseOutcome.UNCERTAIN,
                              message="ISQUAREDATA rejected the education purchase")

    monkeypatch.setattr(IsquareDataAdapter, "submit_education_purchase", submit_education)
    response = client.post("/api/purchase-education", json={
        "service_id": 12, "quantity": 2, "phone_number": "08012345678",
        "email_address": "student@example.com", "pin": "1234"})
    assert response.status_code == 202
    row = tx_status(response.json()["reference"])
    assert row["status"] == "pending" and row["amount"] == 2193 * 2


def test_education_validation(client, isquare_enabled, monkeypatch):
    email, user_id = account(client)
    login(client, email)
    fund(user_id, 100000)
    set_purchase_outcome(monkeypatch)
    base = {"phone_number": "08012345678", "email_address": "s@example.com", "pin": "1234"}
    assert client.post("/api/purchase-education", json={**base, "service_id": 25, "quantity": 1}).status_code == 400  # inactive
    assert client.post("/api/purchase-education", json={**base, "service_id": 11, "quantity": 0}).status_code == 400
    assert client.post("/api/purchase-education", json={**base, "service_id": 11, "quantity": 1, "email_address": "bad"}).status_code == 400
    with db_session() as db:
        assert q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar() == 100000
