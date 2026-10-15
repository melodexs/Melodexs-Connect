"""Explicit PostgreSQL-only race tests; never run against production."""
import asyncio
import hashlib
import os
import queue
import secrets
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app import main
from app.admin_routes import resolve_pending_purchase_state
from app.database import SessionLocal, db_session, engine, q
from fastapi import HTTPException
from app.rate_limit import allowed
from app.security import password_hash
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_POSTGRES_INTEGRATION") != "1",
    reason="requires an explicitly configured dedicated PostgreSQL test/stage database",
)


def test_concurrent_password_reset_token_is_consumed_once_on_postgresql():
    marker = secrets.token_hex(8)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with db_session() as db:
        user_id = q(db, "INSERT INTO users(name,email,phone,password,balance,kyc_status,is_admin,reset_token_hash,reset_token_expires_at) VALUES('PG reset test',:email,:phone,'old-hash',0,'pending',0,:hash,:expires) RETURNING id", {
            "email": f"pg-reset-{marker}@example.test",
            "phone": f"080{int(marker[:8], 16) % 10**8:08d}", "hash": token_hash,
            "expires": int(time.time() * 1000) + 300_000,
        }).scalar()

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
        q(db, "DELETE FROM users WHERE id=:id", {"id": user_id})


def test_concurrent_reset_token_hash_creation_is_rejected_by_unique_index():
    marker = secrets.token_hex(8)
    token_hash = hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest()
    with db_session() as db:
        ids = [q(db, "INSERT INTO users(name,email,phone,password,balance,kyc_status,is_admin) VALUES(:name,:email,:phone,'old-hash',0,'pending',0) RETURNING id", {
            "name": "PG reset uniqueness test", "email": f"pg-reset-unique-{marker}-{n}@example.test",
            "phone": f"080{(int(marker[:8], 16) + n) % 10**8:08d}",
        }).scalar() for n in range(2)]
    barrier = threading.Barrier(2)

    def assign_hash(user_id):
        try:
            barrier.wait(timeout=5)
            with db_session() as db:
                q(db, "UPDATE users SET reset_token_hash=:hash,reset_token_expires_at=:expiry WHERE id=:id", {
                    "hash": token_hash, "expiry": int(time.time() * 1000) + 300_000, "id": user_id,
                })
            return "created"
        except IntegrityError:
            return "rejected"

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(assign_hash, ids))
        assert sorted(outcomes) == ["created", "rejected"]
        with db_session() as db:
            assert q(db, "SELECT COUNT(*) FROM users WHERE reset_token_hash=:hash", {"hash": token_hash}).scalar() == 1
    finally:
        with db_session() as db:
            q(db, "DELETE FROM users WHERE id IN (:first,:second)", {"first": ids[0], "second": ids[1]})


def test_reset_token_expiring_while_waiting_for_row_lock_is_rejected(monkeypatch):
    """Hold the row, prove the request is waiting, then expire it before release."""
    marker = secrets.token_hex(8)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with db_session() as db:
        user_id = q(db, "INSERT INTO users(name,email,phone,password,balance,kyc_status,is_admin,reset_token_hash,reset_token_expires_at) VALUES('PG reset wait test',:email,:phone,'old-hash',0,'pending',0,:hash,:expires) RETURNING id", {
            "email": f"pg-reset-wait-{marker}@example.test",
            "phone": f"080{int(marker[:8], 16) % 10**8:08d}", "hash": token_hash,
            "expires": int(time.time() * 1000) + 300_000,
        }).scalar()

    lock_owner = SessionLocal()
    lock_owner.begin()
    q(lock_owner, "SELECT id FROM users WHERE id=:id FOR UPDATE", {"id": user_id}).first()
    original_q = main.q
    waiting_pid = queue.Queue()

    def signal_lock_wait(db, statement, params=None):
        if "FOR UPDATE" in statement.upper():
            waiting_pid.put(original_q(db, "SELECT pg_backend_pid()").scalar())
        return original_q(db, statement, params)

    monkeypatch.setattr(main, "q", signal_lock_wait)

    def redeem():
        try:
            main.reset_password({"token": token, "newPassword": "must-not-be-set"})
            return "success"
        except HTTPException as exc:
            return exc.detail

    workers = ThreadPoolExecutor(max_workers=1)
    try:
        result = workers.submit(redeem)
        pid = waiting_pid.get(timeout=5)
        deadline = time.monotonic() + 10
        is_waiting = False
        while time.monotonic() < deadline and not result.done():
            with db_session() as monitor:
                wait_type = q(monitor, "SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid", {"pid": pid}).scalar()
            if wait_type == "Lock":
                is_waiting = True
                break
            time.sleep(0.01)
        if not is_waiting:
            lock_owner.rollback()
            raise AssertionError("reset request did not enter a PostgreSQL lock wait")
        q(lock_owner, "UPDATE users SET reset_token_expires_at=(EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT - 1 WHERE id=:id", {"id": user_id})
        lock_owner.commit()
        assert result.result(timeout=5) == "This password reset link has expired. Please request a new one."
    finally:
        lock_owner.rollback()
        lock_owner.close()
        workers.shutdown(wait=True)
        with db_session() as db:
            q(db, "DELETE FROM users WHERE id=:id", {"id": user_id})


def test_concurrent_rate_limit_boundary_on_postgresql(monkeypatch):
    from app import rate_limit

    path = "/pg/concurrent-limit"
    key = "pg-concurrent-limit-" + secrets.token_hex(8)
    monkeypatch.setitem(rate_limit.LIMITS, path, (4, 60))

    def hit(_):
        return allowed(path, key)[0]

    with ThreadPoolExecutor(max_workers=8) as workers:
        outcomes = list(workers.map(hit, range(12)))
    assert sum(outcomes) == 4
    with db_session() as db:
        q(db, "DELETE FROM api_rate_limits WHERE rate_key=:key", {"key": key})


def test_concurrent_paystack_credit_and_purchase_request_are_idempotent(monkeypatch):
    marker = secrets.token_hex(8)
    with db_session() as db:
        user_id = q(db, "INSERT INTO users(name,email,phone,password,balance,kyc_status,is_admin) VALUES(:name,:email,:phone,'test-hash',0,'pending',0) RETURNING id", {"name":"PG Race Test", "email":f"pg-race-{marker}@example.test", "phone":f"080{int(marker[:8],16)%10**8:08d}"}).scalar()
        funding_ref = "pg-funding-" + marker
        q(db, "INSERT INTO transactions(user_id,type,amount,status,reference) VALUES(:id,'wallet_funding',100,'pending',:ref)", {"id":user_id,"ref":funding_ref})
    payment = {"status":"success", "currency":"NGN", "amount":10000, "reference":funding_ref, "metadata":{"user_id":str(user_id)}}

    def credit_once(_):
        return asyncio.run(main.credit_paystack(funding_ref, payment))

    with ThreadPoolExecutor(max_workers=8) as workers:
        outcomes = list(workers.map(credit_once, range(8)))
    with db_session() as db:
        assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id":user_id}).scalar()) == 100
        assert q(db, "SELECT status FROM transactions WHERE reference=:ref", {"ref":funding_ref}).scalar() == "successful"

    calls = 0
    async def provider_purchase(payload):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.15)
        class Response:
            status_code = 200
            def json(self): return {"success":True,"data":{"reference":"provider-"+marker}}
        return Response()

    monkeypatch.setattr(main, "wise_purchase", provider_purchase)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as sync_client:
        # Use an authenticated session inserted directly with the same signed
        # cookie helpers; no password/provider behavior is under test here.
        from fastapi import Response
        from app.security import new_session, password_hash
        cookie_response = Response()
        new_session(cookie_response, int(user_id))
        cookie = cookie_response.headers.get("set-cookie")
        assert cookie
        cookie_pair = cookie.split(";", 1)[0]
        with db_session() as db:
            q(db, "UPDATE users SET purchase_pin=:pin,balance=200 WHERE id=:id", {"id":user_id,"pin":password_hash("1234")})
            q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,provider_package_code,source,category,provider_available) VALUES('MTN',:plan,50,50,1,'mtn',:code,'wisesub','General',1)", {"plan":"Race " + marker,"code":"race-pkg-"+marker})
        request_id = "same-request-" + marker
        payload = {"network":"MTN","phone":"08012345678","plan":"Race " + marker,"pin":"1234","amount":50,"expectedPrice":50,"requestId":request_id}

        async def issue_twice():
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", cookies={cookie_pair.split("=",1)[0]:cookie_pair.split("=",1)[1]}) as client:
                return await asyncio.gather(client.post("/api/purchase-data", json=payload), client.post("/api/purchase-data", json=payload))

        results = asyncio.run(issue_twice())
        assert all(result.status_code in {200, 202} for result in results)
        assert calls == 1
    with db_session() as db:
        assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id":user_id}).scalar()) == 150
        assert q(db, "SELECT COUNT(*) FROM transactions WHERE user_id=:id AND idempotency_key=:key", {"id":user_id,"key":request_id}).scalar() == 1

    refund_ref = "pg-refund-" + marker
    with db_session() as db:
        q(db, "UPDATE users SET balance=125 WHERE id=:id", {"id":user_id})
        refund_tx_id = q(db, "INSERT INTO transactions(user_id,type,amount,status,reference,description) VALUES(:id,'debit',25,'pending',:ref,'concurrent refund test') RETURNING id", {"id":user_id,"ref":refund_ref}).scalar()

    def refund_once(_):
        try:
            resolve_pending_purchase_state(refund_tx_id, "failed", int(user_id))
            return "refunded"
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        refund_outcomes = list(workers.map(refund_once, range(2)))
    assert sorted(str(value) for value in refund_outcomes) == ["409", "refunded"]
    with db_session() as db:
        assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id":user_id}).scalar()) == 150
        assert q(db, "SELECT status FROM transactions WHERE id=:id", {"id":refund_tx_id}).scalar() == "failed"


def _schema_problems(table_details):
    keys = (
        "missing",
        "incompatible_types",
        "incompatible_defaults",
        "unexpected_nullable_columns",
        "missing_constraints",
        "missing_indexes",
        "incompatible_indexes",
        "missing_generated_id_defaults",
    )
    return {key: table_details[key] for key in keys if table_details.get(key)}


def test_schema_check_passes_on_migrated_disposable_postgres():
    """Startup already validated the schema; assert it explicitly here."""
    from app.schema_check import inspect_schema

    assert engine.dialect.name == "postgresql"
    problems = {table: _schema_problems(details) for table, details in inspect_schema().items()}
    assert not any(problems.values()), problems


def test_schema_check_detects_absent_or_redefined_reset_token_index():
    """A same-named index is not accepted without the exact definition."""
    from app.schema_check import inspect_schema

    assert engine.dialect.name == "postgresql"
    correct = ("CREATE UNIQUE INDEX uq_users_reset_token_hash ON public.users "
               "USING btree (reset_token_hash) WHERE (reset_token_hash IS NOT NULL)")
    try:
        with db_session() as db:
            q(db, "DROP INDEX uq_users_reset_token_hash")
        details = inspect_schema()["users"]
        assert "uq_users_reset_token_hash" in details["missing_indexes"]
        assert "uq_users_reset_token_hash" in details["incompatible_indexes"]
        # Redefine the index without the reviewed partial predicate.
        with db_session() as db:
            q(db, "CREATE UNIQUE INDEX uq_users_reset_token_hash ON users(reset_token_hash)")
        details = inspect_schema()["users"]
        assert "uq_users_reset_token_hash" not in details["missing_indexes"]
        incompatible = details["incompatible_indexes"].get("uq_users_reset_token_hash")
        assert incompatible is not None and incompatible["predicate"] is None
    finally:
        with db_session() as db:
            q(db, "DROP INDEX IF EXISTS uq_users_reset_token_hash")
            q(db, correct)
    details = inspect_schema()["users"]
    assert not _schema_problems(details)
