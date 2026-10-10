"""Explicit PostgreSQL-only race tests; never run against production."""
import asyncio
import os
import secrets
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app import main
from app.admin_routes import resolve_pending_purchase_state
from app.database import db_session, q
from fastapi import HTTPException

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_POSTGRES_INTEGRATION") != "1",
    reason="requires an explicitly configured dedicated PostgreSQL test/stage database",
)


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
