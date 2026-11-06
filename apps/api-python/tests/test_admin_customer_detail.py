"""GET /api/admin/users/{id}: the admin's read-only view of one customer.

Risks this pins: only admins may call it, password and PIN hashes never leave
the server, the totals are right (failed and pending money is not counted as
spent), long histories are paged, and the call changes nothing.
"""
import secrets

from fastapi.testclient import TestClient

from app import main
from app.database import db_session, q


def _phone(prefix):
    return f"{prefix}{int(secrets.token_hex(4), 16) % 10**8:08d}"


def _register(client, label, prefix):
    suffix = secrets.token_hex(4)
    response = client.post("/api/register", json={
        "name": f"{label} {suffix}", "email": f"{label.lower()}-{suffix}@example.com",
        "phone": _phone(prefix), "password": "password123"})
    assert response.status_code == 200, response.text
    return response.json()["user"]["id"]


def _make_admin(user_id):
    with db_session() as db:
        q(db, "UPDATE users SET is_admin=1 WHERE id=:id", {"id": user_id})


def _add_tx(user_id, kind, amount, status, description="MTN 1GB Weekly", provider=None, provider_reference=None):
    reference = "T-" + secrets.token_hex(6)
    with db_session() as db:
        q(db, "INSERT INTO transactions(user_id,type,amount,status,reference,description,provider,provider_reference) "
              "VALUES(:u,:t,:a,:s,:r,:d,:p,:pr)",
          {"u": user_id, "t": kind, "a": amount, "s": status, "r": reference, "d": description,
           "p": provider, "pr": provider_reference})
    return reference


def _signed_in_admin_and_customer():
    """One client that is signed in as an admin, plus a separate customer id."""
    with TestClient(main.app) as setup:
        customer_id = _register(setup, "Customer", "081")
    client = TestClient(main.app)
    admin_id = _register(client, "Admin", "082")
    _make_admin(admin_id)
    return client, customer_id


# ---- who may call it -------------------------------------------------------

def test_signed_out_visitors_are_rejected():
    with TestClient(main.app) as client:
        assert client.get("/api/admin/users/1").status_code == 401


def test_a_normal_customer_cannot_read_anyone_including_themselves():
    with TestClient(main.app) as client:
        own_id = _register(client, "Plain", "083")
        assert client.get(f"/api/admin/users/{own_id}").status_code == 403
        assert client.get("/api/admin/users/1").status_code == 403


def test_a_missing_customer_is_a_clean_404():
    client, _ = _signed_in_admin_and_customer()
    response = client.get("/api/admin/users/99999999")
    assert response.status_code == 404
    assert response.json() == {"success": False, "message": "Customer not found"}


def test_a_non_numeric_id_is_rejected_not_a_server_error():
    client, _ = _signed_in_admin_and_customer()
    assert client.get("/api/admin/users/abc").status_code == 400


# ---- what it must never reveal ---------------------------------------------

def test_password_and_pin_hashes_never_appear_anywhere_in_the_response():
    client, customer_id = _signed_in_admin_and_customer()
    with db_session() as db:
        q(db, "UPDATE users SET purchase_pin=:p WHERE id=:id", {"p": "$2b$12$PINHASHMARKERxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "id": customer_id})
        stored = q(db, "SELECT password FROM users WHERE id=:id", {"id": customer_id}).scalar()
    body = client.get(f"/api/admin/users/{customer_id}")
    assert body.status_code == 200
    text = body.text
    assert stored not in text and "PINHASHMARKER" not in text
    customer = body.json()["customer"]
    for forbidden in ("password", "purchase_pin", "reset_token_hash", "reset_token_expires_at"):
        assert forbidden not in customer, forbidden
    assert set(customer) == {"id", "name", "email", "phone", "balance", "virtual_account_number",
                             "virtual_bank_name", "kyc_status", "is_admin", "created_at"}


# ---- the numbers -----------------------------------------------------------

def test_summary_counts_only_successful_money_as_spent_and_funded():
    client, customer_id = _signed_in_admin_and_customer()
    _add_tx(customer_id, "wallet_funding", 5000, "successful", "Wallet funding")
    _add_tx(customer_id, "wallet_funding", 2000, "pending", "Wallet funding")
    _add_tx(customer_id, "debit", 459, "successful")
    _add_tx(customer_id, "debit", 200, "successful", "Airtime")
    _add_tx(customer_id, "debit", 918, "failed")
    _add_tx(customer_id, "debit", 100, "pending")
    data = client.get(f"/api/admin/users/{customer_id}").json()
    summary = data["summary"]
    assert summary["totalTransactions"] == 6
    assert summary["pending"] == 2 and summary["failed"] == 1
    assert summary["purchases"] == 2
    assert summary["totalSpent"] == 659.0, "failed and pending purchases must not count as spent"
    assert summary["totalFunded"] == 5000.0, "a pending top-up must not count as funded"
    assert summary["lastActivity"]


def test_a_customer_with_no_activity_gets_zeroes_not_errors():
    client, customer_id = _signed_in_admin_and_customer()
    data = client.get(f"/api/admin/users/{customer_id}").json()
    assert data["transactions"] == []
    assert data["summary"] == {"totalTransactions": 0, "pending": 0, "failed": 0, "purchases": 0,
                               "totalSpent": 0.0, "totalFunded": 0.0, "lastActivity": None}
    assert data["paging"]["hasMore"] is False


def test_only_that_customers_transactions_are_returned():
    client, customer_id = _signed_in_admin_and_customer()
    with TestClient(main.app) as other_client:
        other_id = _register(other_client, "Other", "084")
    mine = _add_tx(customer_id, "debit", 111, "successful")
    theirs = _add_tx(other_id, "debit", 222, "successful")
    refs = [t["reference"] for t in client.get(f"/api/admin/users/{customer_id}").json()["transactions"]]
    assert mine in refs and theirs not in refs


def test_admin_sees_the_full_description_and_provider_for_support():
    """Unlike the customer wallet, support needs the internal part."""
    client, customer_id = _signed_in_admin_and_customer()
    _add_tx(customer_id, "debit", 459, "pending", "MTN 1GB Weekly | ISQUAREDATA rejected, requery 404",
            provider="isquaredata", provider_reference="ISQ-123")
    tx = client.get(f"/api/admin/users/{customer_id}").json()["transactions"][0]
    assert tx["description"] == "MTN 1GB Weekly | ISQUAREDATA rejected, requery 404"
    assert tx["provider"] == "isquaredata" and tx["provider_reference"] == "ISQ-123"


def test_newest_transaction_comes_first():
    client, customer_id = _signed_in_admin_and_customer()
    first = _add_tx(customer_id, "debit", 1, "successful")
    second = _add_tx(customer_id, "debit", 2, "successful")
    refs = [t["reference"] for t in client.get(f"/api/admin/users/{customer_id}").json()["transactions"]]
    assert refs.index(second) < refs.index(first)


# ---- paging ----------------------------------------------------------------

def test_history_is_paged_and_reports_whether_there_is_more():
    client, customer_id = _signed_in_admin_and_customer()
    for i in range(7):
        _add_tx(customer_id, "debit", 10 + i, "successful")
    page1 = client.get(f"/api/admin/users/{customer_id}?limit=3&offset=0").json()
    page2 = client.get(f"/api/admin/users/{customer_id}?limit=3&offset=3").json()
    page3 = client.get(f"/api/admin/users/{customer_id}?limit=3&offset=6").json()
    assert [len(p["transactions"]) for p in (page1, page2, page3)] == [3, 3, 1]
    assert [p["paging"]["hasMore"] for p in (page1, page2, page3)] == [True, True, False]
    ids = [t["id"] for p in (page1, page2, page3) for t in p["transactions"]]
    assert len(ids) == len(set(ids)) == 7, "no row repeated or skipped between pages"
    assert page1["summary"]["totalTransactions"] == 7, "the summary covers all rows, not just the page"


def test_absurd_limits_are_clamped_not_trusted():
    client, customer_id = _signed_in_admin_and_customer()
    _add_tx(customer_id, "debit", 5, "successful")
    huge = client.get(f"/api/admin/users/{customer_id}?limit=99999999&offset=-5").json()
    assert huge["paging"]["limit"] == 500 and huge["paging"]["offset"] == 0
    tiny = client.get(f"/api/admin/users/{customer_id}?limit=0").json()
    assert tiny["paging"]["limit"] == 1


# ---- read only -------------------------------------------------------------

def test_the_call_changes_nothing():
    client, customer_id = _signed_in_admin_and_customer()
    _add_tx(customer_id, "debit", 459, "pending")
    with db_session() as db:
        q(db, "UPDATE users SET balance=1234.50 WHERE id=:id", {"id": customer_id})

    def snapshot():
        with db_session() as db:
            return (
                [tuple(r) for r in q(db, "SELECT id,balance,kyc_status,is_admin FROM users ORDER BY id").all()],
                [tuple(r) for r in q(db, "SELECT id,user_id,type,amount,status,reference FROM transactions ORDER BY id").all()],
            )

    before = snapshot()
    for _ in range(3):
        assert client.get(f"/api/admin/users/{customer_id}").status_code == 200
    assert snapshot() == before


def test_only_get_is_allowed():
    client, customer_id = _signed_in_admin_and_customer()
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, "request")(method.upper(), f"/api/admin/users/{customer_id}")
        assert response.status_code in (404, 405), (method, response.status_code)
