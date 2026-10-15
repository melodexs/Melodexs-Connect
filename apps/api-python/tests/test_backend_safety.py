import hashlib
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app import main
from app.config import (
    WISESUB_LIVE_BASE_URL,
    Settings,
    normalize_runtime_environment,
    validate_wisesub_configuration,
    validate_wisesub_environment,
    wisesub_base_url,
    wisesub_recipient,
)
from app.database import db_session, q
from app.rate_limit import allowed
from app.security import password_check, password_hash


def _new_reset_user(token=None, expires_at=None):
    marker = secrets.token_hex(8)
    token = token or secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with db_session() as db:
        user_id = q(db, "INSERT INTO users(name,email,phone,password,balance,kyc_status,is_admin,reset_token_hash,reset_token_expires_at) VALUES(:name,:email,:phone,:password,0,'pending',0,:hash,:expires) RETURNING id", {
            "name": "Reset Test", "email": f"reset-{marker}@example.test",
            "phone": f"080{int(marker[:8], 16) % 10**8:08d}",
            "password": password_hash("old-password"), "hash": token_hash,
            "expires": expires_at if expires_at is not None else int(time.time() * 1000) + 300_000,
        }).scalar()
    return int(user_id), token


def _new_reset_session(user_id):
    marker = secrets.token_hex(8)
    sid = f"reset-edge-session-{marker}"
    session_data = json.dumps({"userId": user_id})
    session_expiry = int(time.time() * 1000) + 60_000
    with db_session() as db:
        q(db, "INSERT INTO sessions(sid,sess,expire) VALUES(:sid,:sess,:expire)", {
            "sid": sid, "sess": session_data,
            "expire": session_expiry,
        })
    return sid, session_data, session_expiry


def test_password_reset_token_is_single_use_and_keeps_success_response():
    user_id, token = _new_reset_user()
    result = main.reset_password({"token": token, "newPassword": "new-password"})
    assert result == {"success": True, "message": "Password reset successfully. You can now log in."}
    with db_session() as db:
        row = q(db, "SELECT password,reset_token_hash,reset_token_expires_at FROM users WHERE id=:id", {"id": user_id}).mappings().one()
    assert password_check("new-password", row["password"])
    assert row["reset_token_hash"] is None
    assert row["reset_token_expires_at"] is None
    with pytest.raises(HTTPException) as exc:
        main.reset_password({"token": token, "newPassword": "another-password"})
    assert exc.value.status_code == 400
    assert exc.value.detail == "This password reset link is invalid or has already been used."


def test_concurrent_sqlite_password_reset_consumes_token_once():
    user_id, token = _new_reset_user()

    def consume(_):
        try:
            main.reset_password({"token": token, "newPassword": "concurrent-password"})
            return "success"
        except HTTPException as exc:
            assert exc.status_code == 400
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(consume, range(2)))
    assert outcomes.count("success") == 1
    assert outcomes.count("rejected") == 1
    with db_session() as db:
        assert q(db, "SELECT reset_token_hash FROM users WHERE id=:id", {"id": user_id}).scalar() is None


def test_duplicate_reset_hash_fails_closed_without_changing_either_account():
    duplicate_token = secrets.token_urlsafe(32)
    user_ids = []
    # Simulate pre-migration legacy data. The index is restored in finally;
    # this test does not leave duplicate rows in the test database.
    with db_session() as db:
        q(db, "DROP INDEX IF EXISTS uq_users_reset_token_hash")
    try:
        user_ids.append(_new_reset_user(duplicate_token)[0])
        user_ids.append(_new_reset_user(duplicate_token)[0])

        with pytest.raises(HTTPException) as exc:
            main.reset_password({"token": duplicate_token, "newPassword": "must-not-be-set"})
        assert exc.value.status_code == 400
        assert exc.value.detail == "This password reset link is invalid or has already been used."
        with db_session() as db:
            rows = q(db, "SELECT id,password,reset_token_hash FROM users WHERE id IN (:first,:second) ORDER BY id", {
                "first": user_ids[0], "second": user_ids[1],
            }).mappings().all()
        assert len(rows) == 2
        assert all(password_check("old-password", row["password"]) for row in rows)
        assert all(row["reset_token_hash"] == hashlib.sha256(duplicate_token.encode()).hexdigest() for row in rows)
    finally:
        with db_session() as db:
            if user_ids:
                for user_id in user_ids:
                    q(db, "DELETE FROM users WHERE id=:id", {"id": user_id})
            q(db, "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_reset_token_hash ON users(reset_token_hash) WHERE reset_token_hash IS NOT NULL")


def test_expired_reset_token_is_rejected_without_changing_password():
    user_id, token = _new_reset_user(expires_at=int(time.time() * 1000) - 1)
    with pytest.raises(HTTPException) as exc:
        main.reset_password({"token": token, "newPassword": "must-not-be-set"})
    assert exc.value.status_code == 400
    assert exc.value.detail == "This password reset link has expired. Please request a new one."
    with db_session() as db:
        row = q(db, "SELECT password,reset_token_hash FROM users WHERE id=:id", {"id": user_id}).mappings().one()
    assert password_check("old-password", row["password"])
    assert row["reset_token_hash"] == hashlib.sha256(token.encode()).hexdigest()


def test_unknown_reset_token_leaves_account_and_session_unchanged():
    user_id, valid_token = _new_reset_user()
    sid, session_data, session_expiry = _new_reset_session(user_id)
    unknown_token = secrets.token_urlsafe(32)
    with db_session() as db:
        original_expiry = q(db, "SELECT reset_token_expires_at FROM users WHERE id=:id", {"id": user_id}).scalar()

    with pytest.raises(HTTPException) as exc:
        main.reset_password({"token": unknown_token, "newPassword": "must-not-be-set"})
    assert exc.value.status_code == 400
    assert exc.value.detail == "This password reset link is invalid or has already been used."

    with db_session() as db:
        row = q(db, "SELECT password,reset_token_hash=:expected_hash AS token_matches,reset_token_expires_at FROM users WHERE id=:id", {
            "expected_hash": hashlib.sha256(valid_token.encode()).hexdigest(), "id": user_id,
        }).mappings().one()
        session_count = q(db, "SELECT COUNT(*) FROM sessions WHERE sid=:sid AND sess=:sess AND expire=:expire", {
            "sid": sid, "sess": session_data, "expire": session_expiry,
        }).scalar()
    assert password_check("old-password", row["password"])
    assert row["token_matches"] is True
    assert row["reset_token_expires_at"] == original_expiry
    assert session_count == 1


def test_reset_token_expiry_boundary_is_rejected_without_state_changes(monkeypatch):
    fixed_now_ms = 1_800_000_000_000
    user_id, token = _new_reset_user(expires_at=fixed_now_ms)
    sid, session_data, session_expiry = _new_reset_session(user_id)
    monkeypatch.setattr(main, "_database_epoch_millis_sql", lambda: str(fixed_now_ms))

    with pytest.raises(HTTPException) as exc:
        main.reset_password({"token": token, "newPassword": "must-not-be-set"})
    assert exc.value.status_code == 400
    assert exc.value.detail == "This password reset link has expired. Please request a new one."

    with db_session() as db:
        row = q(db, "SELECT password,reset_token_hash=:expected_hash AS token_matches,reset_token_expires_at FROM users WHERE id=:id", {
            "expected_hash": hashlib.sha256(token.encode()).hexdigest(), "id": user_id,
        }).mappings().one()
        session_count = q(db, "SELECT COUNT(*) FROM sessions WHERE sid=:sid AND sess=:sess AND expire=:expire", {
            "sid": sid, "sess": session_data, "expire": session_expiry,
        }).scalar()
    assert password_check("old-password", row["password"])
    assert row["token_matches"] is True
    assert row["reset_token_expires_at"] == fixed_now_ms
    assert session_count == 1


def test_password_update_failure_rolls_back_token_and_preserves_session(monkeypatch):
    user_id, token = _new_reset_user()
    sid, session_data, session_expiry = _new_reset_session(user_id)
    with db_session() as db:
        original_expiry = q(db, "SELECT reset_token_expires_at FROM users WHERE id=:id", {"id": user_id}).scalar()
    original_q = main.q

    def fail_password_update(db, statement, params=None):
        if statement.startswith("UPDATE users SET password="):
            raise RuntimeError("simulated password update failure")
        return original_q(db, statement, params)

    monkeypatch.setattr(main, "q", fail_password_update)
    with pytest.raises(RuntimeError, match="simulated password update failure"):
        main.reset_password({"token": token, "newPassword": "must-not-be-set"})

    with db_session() as db:
        row = q(db, "SELECT password,reset_token_hash=:expected_hash AS token_matches,reset_token_expires_at FROM users WHERE id=:id", {
            "expected_hash": hashlib.sha256(token.encode()).hexdigest(), "id": user_id,
        }).mappings().one()
        session_count = q(db, "SELECT COUNT(*) FROM sessions WHERE sid=:sid AND sess=:sess AND expire=:expire", {
            "sid": sid, "sess": session_data, "expire": session_expiry,
        }).scalar()
    assert password_check("old-password", row["password"])
    assert row["token_matches"] is True
    assert row["reset_token_expires_at"] == original_expiry
    assert session_count == 1


def test_sqlite_unique_partial_index_rejects_duplicate_reset_token_hash():
    from app.database import engine

    assert engine.dialect.name == "sqlite"
    with db_session() as db:
        index = q(db, "SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_users_reset_token_hash'").scalar()
    assert index is not None
    token = secrets.token_urlsafe(32)
    _new_reset_user(token)
    with pytest.raises(IntegrityError):
        _new_reset_user(token)


def test_password_reset_session_cleanup_failure_rolls_back_token_and_password(monkeypatch):
    user_id, token = _new_reset_user()

    def fail_revocation(_db, _user_id):
        raise RuntimeError("simulated cleanup failure")

    monkeypatch.setattr(main, "_revoke_user_sessions", fail_revocation)
    with pytest.raises(RuntimeError, match="simulated cleanup failure"):
        main.reset_password({"token": token, "newPassword": "must-not-be-set"})
    with db_session() as db:
        row = q(db, "SELECT password,reset_token_hash FROM users WHERE id=:id", {"id": user_id}).mappings().one()
    assert password_check("old-password", row["password"])
    assert row["reset_token_hash"] == hashlib.sha256(token.encode()).hexdigest()


def test_password_reset_session_cleanup_matches_exact_json_user_id():
    marker = secrets.token_hex(8)
    sid_5, sid_50 = f"reset-sid-5-{marker}", f"reset-sid-50-{marker}"
    with db_session() as db:
        q(db, "INSERT INTO sessions(sid,sess,expire) VALUES(:sid5,:sess5,:expire),(:sid50,:sess50,:expire)", {
            "sid5": sid_5, "sess5": json.dumps({"userId": 5}),
            "sid50": sid_50, "sess50": json.dumps({"userId": 50}),
            "expire": int(time.time() * 1000) + 60_000,
        })
        main._revoke_user_sessions(db, 5)
    with db_session() as db:
        remaining = {row["sid"] for row in q(db, "SELECT sid FROM sessions WHERE sid IN (:sid5,:sid50)", {"sid5": sid_5, "sid50": sid_50}).mappings()}
    assert remaining == {sid_50}


def test_rate_limit_atomic_counter_expiry_and_concurrent_boundary(monkeypatch):
    from app import rate_limit

    monkeypatch.setitem(rate_limit.LIMITS, "/test/atomic-limit", (4, 60))
    monkeypatch.setattr(rate_limit.time, "time", lambda: 2_000_000_000)
    key = "test-atomic-" + secrets.token_hex(8)

    def hit(_):
        return allowed("/test/atomic-limit", key)[0]

    with ThreadPoolExecutor(max_workers=8) as workers:
        outcomes = list(workers.map(hit, range(12)))
    assert sum(outcomes) == 4
    monkeypatch.setattr(rate_limit.time, "time", lambda: 2_000_000_061)
    assert allowed("/test/atomic-limit", key) == (True, "")


@pytest.mark.parametrize(
    "values",
    [
        {"node_env": "production"},
        {"node_env": "production", "wisesub_environment": ""},
        {"node_env": "production", "wisesub_environment": "sandbox"},
        {"node_env": "production", "wisesub_environment": "test"},
        {"node_env": "production", "wisesub_environment": " live "},
    ],
)
def test_production_wisesub_configuration_rejects_missing_invalid_and_test(monkeypatch, values):
    monkeypatch.delenv("WISESUB_ENVIRONMENT", raising=False)
    config = Settings(_env_file=None, **values)
    with pytest.raises(RuntimeError):
        validate_wisesub_environment(config)


def test_production_wisesub_configuration_accepts_explicit_live():
    config = Settings(_env_file=None, node_env="production", wisesub_environment="live")
    validate_wisesub_environment(config)


def test_production_wisesub_configuration_accepts_explicit_environment_variable(monkeypatch):
    monkeypatch.setenv("WISESUB_ENVIRONMENT", "live")
    config = Settings(_env_file=None, node_env="production")
    assert "wisesub_environment" in config.model_fields_set
    validate_wisesub_environment(config)


def test_runtime_environment_must_be_explicit_and_is_normalized(monkeypatch):
    monkeypatch.delenv("NODE_ENV", raising=False)
    with pytest.raises(RuntimeError, match="NODE_ENV must be explicitly set"):
        normalize_runtime_environment(Settings(_env_file=None))
    normalized = Settings(_env_file=None, node_env="  Production ")
    assert normalize_runtime_environment(normalized) == "production"
    invalid = Settings(_env_file=None, node_env="prod")
    with pytest.raises(RuntimeError, match="NODE_ENV must be explicitly set"):
        normalize_runtime_environment(invalid)


def test_production_wisesub_endpoint_must_match_repository_live_endpoint():
    valid = Settings(
        _env_file=None,
        node_env="production",
        wisesub_environment="live",
        wisesub_base_url=WISESUB_LIVE_BASE_URL,
    )
    assert validate_wisesub_configuration(valid) == WISESUB_LIVE_BASE_URL
    with_slash = Settings(
        _env_file=None,
        node_env="production",
        wisesub_environment="live",
        wisesub_base_url=WISESUB_LIVE_BASE_URL + "/",
    )
    assert validate_wisesub_configuration(with_slash) == WISESUB_LIVE_BASE_URL


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a URL",
        "http://app.wisesub.com.ng/api/partner/v1",
        "https://app.wisesub.com.ng.attacker.example/api/partner/v1",
        "https://user@app.wisesub.com.ng/api/partner/v1",
        "https://app.wisesub.com.ng/api/partner/v1?redirect=elsewhere",
        "https://app.wisesub.com.ng/api/partner/v1/extra",
        " https://app.wisesub.com.ng/api/partner/v1 ",
    ],
)
def test_production_wisesub_endpoint_rejects_mismatch_or_malformed_url(url):
    config = Settings(
        _env_file=None,
        node_env="production",
        wisesub_environment="live",
        wisesub_base_url=url,
    )
    with pytest.raises(RuntimeError):
        validate_wisesub_configuration(config)


def test_wisesub_runtime_rechecks_production_mode_before_headers_and_recipient(monkeypatch):
    from app import config as config_module
    from app.providers import wise_headers

    monkeypatch.setattr(config_module, "PRODUCTION_MODE", True)
    monkeypatch.setattr(config_module.settings, "wisesub_environment", "test")
    with pytest.raises(RuntimeError, match="WISESUB_ENVIRONMENT=live"):
        wisesub_recipient("08012345678")
    with pytest.raises(RuntimeError, match="WISESUB_ENVIRONMENT=live"):
        wise_headers()

    monkeypatch.setattr(config_module.settings, "wisesub_environment", "live")
    monkeypatch.setattr(config_module.settings, "wisesub_base_url", "https://attacker.example/api")
    with pytest.raises(RuntimeError, match="approved WiseSub endpoint"):
        wisesub_base_url()

    monkeypatch.setattr(config_module.settings, "wisesub_base_url", WISESUB_LIVE_BASE_URL)
    assert wisesub_recipient("08012345678") == "08012345678"
    assert wise_headers()["X-Environment"] == "live"


def test_wisesub_test_recipient_remains_available_outside_production(monkeypatch):
    from app import config as config_module

    monkeypatch.setattr(config_module, "PRODUCTION_MODE", False)
    monkeypatch.setattr(config_module.settings, "wisesub_environment", "test")
    assert wisesub_recipient("08012345678") == "08011111111"


@pytest.mark.parametrize(
    ("environment", "should_start"),
    [(None, False), ("sandbox", False), ("test", False), ("live", True)],
)
def test_production_startup_requires_explicit_live_wisesub(monkeypatch, environment, should_start):
    from app import main, schema_check

    monkeypatch.delenv("WISESUB_ENVIRONMENT", raising=False)
    values = {"node_env": "production"}
    values["wisesub_base_url"] = WISESUB_LIVE_BASE_URL
    if environment is not None:
        values["wisesub_environment"] = environment
    monkeypatch.setattr(main, "settings", Settings(_env_file=None, **values))
    monkeypatch.setattr(main, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    monkeypatch.setattr(schema_check, "inspect_schema", lambda: {})
    if should_start:
        main.startup()
    else:
        with pytest.raises(RuntimeError):
            main.startup()


def test_nonproduction_wisesub_configuration_keeps_test_default():
    config = Settings(_env_file=None, node_env="test")
    assert config.wisesub_environment == "test"
    validate_wisesub_environment(config)
