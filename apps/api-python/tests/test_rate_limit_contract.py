"""The limiter's table of limits and its allow/deny behaviour."""
import secrets

import pytest

from app import rate_limit
from app.database import db_session, q


def test_every_money_and_auth_route_has_a_limit():
    for route in ("/api/login", "/api/register", "/api/forgot-password", "/api/reset-password",
                  "/api/purchase-data", "/api/purchase-airtime", "/api/fund-wallet", "/api/fund-wallet/verify",
                  "/api/purchase-pin/verify"):
        limit, window = rate_limit.LIMITS[route]
        assert limit > 0 and window > 0, route


def test_password_guessing_is_limited_more_tightly_than_normal_use():
    assert rate_limit.LIMITS["/api/forgot-password"][0] <= rate_limit.LIMITS["/api/purchase-data"][0]
    assert rate_limit.LIMITS["/api/login"][0] <= 20


def test_an_unlisted_route_is_never_limited():
    assert rate_limit.allowed("/api/status", "any-key") == (True, "")


def test_the_limit_allows_exactly_n_then_refuses_with_the_right_message():
    path, key = "/api/login", "contract-" + secrets.token_hex(4)
    limit = rate_limit.LIMITS[path][0]
    try:
        for _ in range(limit):
            assert rate_limit.allowed(path, key) == (True, "")
        ok, message = rate_limit.allowed(path, key)
        assert ok is False and message == "Too many login attempts. Please try again later."
        # The app builds keys as "<ip>:<path>", so each route counts on its own.
        ok, _ = rate_limit.allowed("/api/fund-wallet", key + ":/api/fund-wallet")
        assert ok is True, "a different route has its own counter"
    finally:
        with db_session() as db:
            q(db, "DELETE FROM api_rate_limits WHERE rate_key LIKE :k", {"k": f"%{key}%"})


def test_a_window_that_has_expired_starts_a_fresh_count():
    path, key = "/api/forgot-password", "contract-" + secrets.token_hex(4)
    limit, window = rate_limit.LIMITS[path]
    try:
        with db_session() as db:
            for _ in range(limit):
                assert rate_limit._consume(db, path, key, 1_000, limit, window)[0]
            assert rate_limit._consume(db, path, key, 1_000, limit, window)[0] is False
            assert rate_limit._consume(db, path, key, 1_000 + window + 1, limit, window)[0] is True
    finally:
        with db_session() as db:
            q(db, "DELETE FROM api_rate_limits WHERE rate_key=:k", {"k": key})
