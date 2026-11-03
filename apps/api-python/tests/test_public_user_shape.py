"""public_user() is the only thing standing between a database row and the wire.

It must never leak a password hash, a purchase PIN, a reset token or an internal
column, whatever extra columns a future migration adds to `users`.
"""
from app.main import public_user

ROW = {
    "id": 7, "name": "Amaka", "email": "amaka@example.com", "phone": "08030000000",
    "balance": 1250.5, "virtual_account_number": None, "virtual_bank_name": None,
    "kyc_status": "pending", "is_admin": 0, "created_at": "2026-10-01T10:00:00",
    "profile_image": None, "purchase_pin": "hashed-pin",
    "password": "$2b$10$abcdefghijklmnopqrstuv",
    "reset_token_hash": "deadbeef", "reset_token_expires_at": 1999999999999,
}

FORBIDDEN = {"password", "purchase_pin", "reset_token_hash", "reset_token_expires_at"}


def test_never_exposes_credentials():
    payload = public_user(ROW)
    assert not (FORBIDDEN & set(payload)), f"leaked: {FORBIDDEN & set(payload)}"


def test_reports_whether_a_pin_exists_without_revealing_it():
    assert public_user(ROW)["has_purchase_pin"] is True
    assert public_user({**ROW, "purchase_pin": None})["has_purchase_pin"] is False


def test_balance_is_always_numeric():
    assert public_user({**ROW, "balance": None})["balance"] == 0.0
    assert public_user(ROW)["balance"] == 1250.5


def test_missing_row_is_none():
    assert public_user(None) is None
