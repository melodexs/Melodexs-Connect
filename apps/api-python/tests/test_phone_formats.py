"""Nigerian numbers typed with +234 (or 234, spaces, dashes) must register.

The sign-up form only accepted 0XXXXXXXXXX, so a user typing +234 806 834 7514
was told the number was invalid. The API now accepts every common spelling and
stores ONE canonical local form, so +2348068347514 and 08068347514 are the same
person: the duplicate check works across spellings and the profile shows one
consistent number.
"""
import secrets

import pytest
from fastapi.testclient import TestClient

from app import main
from app.database import db_session, q


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with db_session() as db:
        q(db, "DELETE FROM users WHERE email LIKE 'phonefmt-%@example.com'")


def _local(suffix: str) -> str:
    return f"080{int(suffix, 16) % 10**8:08d}"


def _register(client, phone, suffix=None, **extra):
    suffix = suffix or secrets.token_hex(4)
    payload = {"name": "Phone Test", "email": f"phonefmt-{suffix}@example.com", "phone": phone,
               "password": "password123", **extra}
    return client.post("/api/register", json=payload)


@pytest.mark.parametrize("raw,expected", [
    ("08068347514", "08068347514"),
    ("+2348068347514", "08068347514"),
    ("2348068347514", "08068347514"),
    ("+234 806 834 7514", "08068347514"),
    ("0806-834-7514", "08068347514"),
    ("  +234(806)8347514 ", "08068347514"),
])
def test_normalizer_maps_every_spelling_to_the_local_form(raw, expected):
    assert main.normalize_nigeria_phone(raw) == expected
    assert main.nigeria_phone(main.normalize_nigeria_phone(raw))


@pytest.mark.parametrize("raw", ["", "123", "+2348068347", "0806834751", "+447911123456", "abcdefghijk", "+234806834751400"])
def test_garbage_and_foreign_numbers_still_fail_validation(raw):
    assert not main.nigeria_phone(main.normalize_nigeria_phone(raw))


@pytest.mark.parametrize("style", ["+234{n}", "234{n}", "+234 {a} {b} {c}"])
def test_register_accepts_plus234_and_stores_the_local_form(style):
    suffix = secrets.token_hex(4)
    local = _local(suffix)            # 0 + 10 digits
    tail = local[1:]                  # 10 digits
    raw = style.format(n=tail, a=tail[:3], b=tail[3:6], c=tail[6:])
    with TestClient(main.app) as client:
        response = _register(client, raw, suffix)
        assert response.status_code == 200, response.text
        assert response.json()["user"]["phone"] == local


def test_the_same_number_in_two_spellings_cannot_register_twice():
    suffix = secrets.token_hex(4)
    local = _local(suffix)
    with TestClient(main.app) as client:
        assert _register(client, local, suffix).status_code == 200
        other = secrets.token_hex(4)
        again = _register(client, "+234" + local[1:], other)
        assert again.status_code == 400
        assert "already exists" in again.json()["message"]


def test_register_still_rejects_an_invalid_number():
    with TestClient(main.app) as client:
        for bad in ("12345", "+44 7911 123456", "0806834751"):
            response = _register(client, bad)
            assert response.status_code == 400, bad
            assert "valid Nigerian phone" in response.json()["message"]
