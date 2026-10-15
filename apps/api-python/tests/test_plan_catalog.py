import asyncio
import secrets
import httpx

from fastapi.testclient import TestClient

from app import main, plan_sync
from app.database import db_session, q


class FakeResponse:
    status_code = 200
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload


class FakeClient:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    async def get(self, url, **kwargs):
        return FakeResponse({"success": True, "data": {"data_bundles": [{"name": "MTN Data", "type": "data", "provider_code": "mtn"}]}})


def test_provider_normalization_uses_documented_fields_and_markup():
    normalized = plan_sync.normalize_package({"package_code": "mtn-code-1", "package_name": "N3,000 10GB - 30 days", "price": "3000"})
    assert normalized["code"] == "mtn-code-1"
    assert normalized["data_size"] == "10GB"
    assert normalized["validity"] == "30 days"
    assert plan_sync.selling_price(3000) == 3060


def test_wisesub_reference_matches_documented_format():
    reference = main.ref()
    assert len(reference) >= 12
    assert reference[:12].isdigit()
    assert reference[12:].isalnum()


def test_sync_is_repeatable_and_preserves_admin_overrides(monkeypatch):
    code = "mtn-stable-" + secrets.token_hex(5)
    monkeypatch.setattr(plan_sync.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    async def one_plan(client, network, code):
        return [plan_sync.normalize_package({"package_code": code, "package_name": "N3,000 10GB - 30 days", "price": "3000"})]
    monkeypatch.setattr(plan_sync, "fetch_network", lambda client, network, provider_code: one_plan(client, network, code))
    first = asyncio.run(plan_sync.synchronize_plans())
    with db_session() as db:
        plan_id = q(db, "SELECT id FROM data_plans WHERE source='wisesub' AND provider_package_code=:code", {"code": code}).scalar()
        q(db, "UPDATE data_plans SET category='SME Data',selling_price_override=3200,selling_price=3200 WHERE id=:id", {"id": plan_id})
    assert first["added"] == 1
    second = asyncio.run(plan_sync.synchronize_plans())
    assert second["updated"] == 1
    with db_session() as db:
        row = q(db, "SELECT provider_cost,selling_price,selling_price_override,category,active,provider_available FROM data_plans WHERE id=:id", {"id": plan_id}).mappings().first()
    assert float(row["provider_cost"]) == 3000
    assert float(row["selling_price"]) == 3200
    assert float(row["selling_price_override"]) == 3200
    assert row["category"] == "SME Data" and row["active"] == 1 and row["provider_available"] == 1


def test_sync_recalculates_price_only_when_no_fixed_override(monkeypatch):
    code = "mtn-auto-" + secrets.token_hex(5)
    cost = 100.0
    monkeypatch.setattr(plan_sync.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    async def package(client, network, provider_code):
        return [plan_sync.normalize_package({"package_code":code,"package_name":f"N100 {code}","price":cost})]
    monkeypatch.setattr(plan_sync, "fetch_network", package)
    asyncio.run(plan_sync.synchronize_plans())
    with db_session() as db:
        row_id = q(db, "SELECT id FROM data_plans WHERE provider_package_code=:code", {"code":code}).scalar()
        assert float(q(db, "SELECT selling_price FROM data_plans WHERE id=:id", {"id":row_id}).scalar()) == 102
    cost = 200.0
    asyncio.run(plan_sync.synchronize_plans())
    with db_session() as db:
        row = q(db, "SELECT selling_price,selling_price_override FROM data_plans WHERE id=:id", {"id":row_id}).mappings().first()
    assert float(row["selling_price"]) == 204 and row["selling_price_override"] is None


def test_partial_provider_failure_does_not_deactivate_existing_plan(monkeypatch):
    monkeypatch.setattr(plan_sync.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    with db_session() as db:
        q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider,provider_code,provider_package_code,source,provider_available) VALUES('MTN','3GB',100,102,1,'wisesub','mtn','mtn-protected','wisesub',1) ON CONFLICT(network,plan) DO UPDATE SET provider_available=1")
    async def fail(client, network, code): raise TimeoutError("mock timeout")
    monkeypatch.setattr(plan_sync, "fetch_network", fail)
    result = asyncio.run(plan_sync.synchronize_plans())
    assert result["outcome"] == "failed"
    with db_session() as db:
        assert q(db, "SELECT provider_available FROM data_plans WHERE provider_package_code='mtn-protected'").scalar() == 1


def test_catalog_filters_unclassified_disabled_and_unavailable_plans():
    category = "SME Data " + secrets.token_hex(3)
    with db_session() as db:
        q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,provider_package_code,source,category,provider_available) VALUES('MTN','9GB',10,100,1,'mtn','catalog-filter-1','wisesub',:category,1) ON CONFLICT(network,plan) DO UPDATE SET active=1,provider_available=1,category=:category", {"category": category})
        q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,provider_package_code,source,category,provider_available) VALUES('MTN','10GB',10,100,0,'mtn','catalog-filter-2','wisesub','Hidden',1) ON CONFLICT(network,plan) DO UPDATE SET active=0,provider_available=1,category='Hidden'")
        q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,provider_package_code,source,category,provider_available) VALUES('MTN','11GB',10,100,1,'mtn','catalog-filter-3','wisesub','Offline',0) ON CONFLICT(network,plan) DO UPDATE SET active=1,provider_available=0,category='Offline'")
        q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,provider_package_code,source,category,provider_available) VALUES('MTN','12GB',10,100,1,'mtn','catalog-filter-4','wisesub',NULL,1) ON CONFLICT(network,plan) DO UPDATE SET active=1,provider_available=1,category=NULL")
    with TestClient(main.app) as client:
        cats = client.get("/api/data-categories?network=MTN").json()["categories"]
        plans = client.get("/api/data-plans", params={"network":"MTN", "category":category}).json()["plans"]
    assert category in [item["category"] for item in cats]
    assert [item["plan"] for item in plans] == ["9GB"]


def test_sync_operation_requires_admin():
    with TestClient(main.app) as client:
        suffix = secrets.token_hex(4)
        client.post("/api/register", json={"name":"Catalog User", "email":f"catalog-{suffix}@example.com", "phone":f"081{int(suffix,16)%10**8:08d}", "password":"password123"})
        assert client.post("/api/admin/data-plans/synchronize").status_code == 403


def test_admin_can_assign_category_and_fix_or_clear_price_override():
    suffix = secrets.token_hex(4)
    with TestClient(main.app) as client:
        response = client.post("/api/register", json={"name":"Plan Admin", "email":f"planadmin-{suffix}@example.com", "phone":f"085{int(suffix,16)%10**8:08d}", "password":"password123"})
        user_id = response.json()["user"]["id"]
        with db_session() as db:
            q(db, "UPDATE users SET is_admin=1 WHERE id=:id", {"id":user_id})
            plan_id = q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,provider_package_code,source,provider_available) VALUES('MTN',:plan,100,102,1,'mtn',:code,'wisesub',1) RETURNING id", {"plan":"Admin " + suffix,"code":"admin-"+suffix}).scalar()
        fixed = client.patch(f"/api/admin/data-plans/{plan_id}", json={"selling_price":150,"category":"Future category"})
        assert fixed.status_code == 200
        assert fixed.json()["plan"]["category"] == "Future category"
        cleared = client.patch(f"/api/admin/data-plans/{plan_id}", json={"selling_price":None})
        assert cleared.status_code == 200
        assert cleared.json()["plan"]["selling_price_override"] is None
        assert float(cleared.json()["plan"]["selling_price"]) == 102


def test_successful_snapshot_marks_removed_package_unavailable(monkeypatch):
    code = "mtn-removed-" + secrets.token_hex(4)
    with db_session() as db:
        q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider,provider_code,provider_package_code,source,provider_available,category) VALUES('MTN',:plan,10,11,1,'wisesub','mtn',:code,'wisesub',1,'General')", {"plan": "Removed " + code, "code": code})
    monkeypatch.setattr(plan_sync.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    async def empty(client, network, provider_code): return []
    monkeypatch.setattr(plan_sync, "fetch_network", empty)
    result = asyncio.run(plan_sync.synchronize_plans())
    assert result["outcome"] == "success" and result["unavailable"] >= 1
    with db_session() as db:
        row = q(db, "SELECT provider_available,active FROM data_plans WHERE provider_package_code=:code", {"code": code}).mappings().first()
    assert row["provider_available"] == 0 and row["active"] == 1


def test_uncertain_purchase_request_id_prevents_second_debit(monkeypatch):
    calls = 0
    async def timeout(payload):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("mock response lost")
    monkeypatch.setattr(main, "wise_purchase", timeout)
    request_id = secrets.token_hex(16)
    plan = "Purchase " + request_id
    with TestClient(main.app) as client:
        suffix = secrets.token_hex(4)
        response = client.post("/api/register", json={"name":"Catalog Buyer", "email":f"buyer-{suffix}@example.com", "phone":f"082{int(suffix,16)%10**8:08d}", "password":"password123"})
        user_id = response.json()["user"]["id"]
        client.post("/api/purchase-pin/set", json={"pin":"1234"})
        with db_session() as db:
            q(db, "UPDATE users SET balance=100 WHERE id=:id", {"id": user_id})
            q(db, "INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,provider_code,provider_package_code,source,category) VALUES('MTN',:plan,50,50,1,'mtn',:code,'wisesub','General')", {"plan":plan,"code":"pkg-"+request_id})
        body = {"network":"MTN", "phone":"08012345678", "plan":plan, "pin":"1234", "amount":50, "expectedPrice":50, "requestId":request_id}
        first = client.post("/api/purchase-data", json=body)
        second = client.post("/api/purchase-data", json=body)
        assert first.status_code == second.status_code == 202
        assert calls == 1
        with db_session() as db:
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id":user_id}).scalar()) == 50
            assert q(db, "SELECT COUNT(*) FROM transactions WHERE user_id=:id AND type='debit'", {"id":user_id}).scalar() == 1


def test_confirmed_provider_failure_refunds_pending_purchase_once(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "wisesub_failure_status_confirmed", True)
    async def status(reference): return FakeResponse({"success": True, "data": {"reference":reference,"status":"failed"}})
    monkeypatch.setattr("app.admin_routes.wise_status", status)
    with TestClient(main.app) as client:
        suffix = secrets.token_hex(4)
        response = client.post("/api/register", json={"name":"Reconcile Admin", "email":f"reconcile-{suffix}@example.com", "phone":f"083{int(suffix,16)%10**8:08d}", "password":"password123"})
        user_id = response.json()["user"]["id"]
        with db_session() as db:
            q(db, "UPDATE users SET is_admin=1,balance=50 WHERE id=:id", {"id":user_id})
            q(db, "INSERT INTO transactions(user_id,type,amount,status,reference,description) VALUES(:id,'debit',50,'pending',:ref,'mock uncertain purchase')", {"id":user_id,"ref":"reconcile-"+suffix})
        first = client.post("/api/admin/purchases/reconcile")
        assert first.status_code == 200
        with db_session() as db:
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id":user_id}).scalar()) == 100
            assert q(db, "SELECT status FROM transactions WHERE reference=:ref", {"ref":"reconcile-"+suffix}).scalar() == "failed"
        client.post("/api/admin/purchases/reconcile")
        with db_session() as db:
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id":user_id}).scalar()) == 100


def test_undocumented_failed_status_is_not_auto_refunded_but_admin_resolution_is_once(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "wisesub_failure_status_confirmed", False)
    async def status(reference): return FakeResponse({"success": True, "data": {"reference":reference,"status":"failed"}})
    monkeypatch.setattr("app.admin_routes.wise_status", status)
    with TestClient(main.app) as client:
        suffix = secrets.token_hex(4)
        response = client.post("/api/register", json={"name":"Review Admin", "email":f"review-{suffix}@example.com", "phone":f"084{int(suffix,16)%10**8:08d}", "password":"password123"})
        user_id = response.json()["user"]["id"]
        with db_session() as db:
            q(db, "UPDATE users SET is_admin=1,balance=25 WHERE id=:id", {"id":user_id})
            tx_id = q(db, "INSERT INTO transactions(user_id,type,amount,status,reference,description) VALUES(:id,'debit',25,'pending',:ref,'uncertain') RETURNING id", {"id":user_id,"ref":"review-"+suffix}).scalar()
        checked = client.post("/api/admin/purchases/reconcile").json()
        assert checked["results"][0]["status"] == "failed_needs_admin_review"
        with db_session() as db:
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id":user_id}).scalar()) == 25
        assert client.post(f"/api/admin/purchases/{tx_id}/resolve", json={"status":"failed"}).status_code == 200
        assert client.post(f"/api/admin/purchases/{tx_id}/resolve", json={"status":"failed"}).status_code == 409
        with db_session() as db:
            assert float(q(db, "SELECT balance FROM users WHERE id=:id", {"id":user_id}).scalar()) == 50
