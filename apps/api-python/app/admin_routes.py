import re
from fastapi import APIRouter, Request, HTTPException
from .database import db_session, q
from .security import require_admin

router = APIRouter()


@router.get("/api/admin/data-plans")
def list_plans(request: Request):
    require_admin(request)
    with db_session() as db:
        rows = q(db, "SELECT id,network,plan,provider_cost,selling_price,(selling_price-provider_cost) margin,active,provider,provider_code,provider_package_code,provider_package_name,data_size,validity,source,last_synced_at,created_at,updated_at FROM data_plans WHERE source IS NOT NULL AND TRIM(source)<>'' ORDER BY selling_price,id").mappings().all()
    return {"success": True, "plans": [dict(row) for row in rows]}


@router.post("/api/admin/data-plans")
def create_plan(request: Request, body: dict):
    require_admin(request)
    network, plan = str(body.get("network") or "").strip(), str(body.get("plan") or "").strip().upper()
    try:
        cost, price = float(body.get("provider_cost")), float(body.get("selling_price"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid pricing values")
    if network not in {"MTN", "Airtel", "Glo", "9mobile"} or not re.fullmatch(r"\d+(?:\.\d+)?(?:MB|GB)", plan, re.I):
        raise HTTPException(400, "Invalid network or plan format")
    if cost < 0 or price <= 0 or price < cost:
        raise HTTPException(400, "Selling price cannot be below provider cost")
    with db_session() as db:
        row = q(db, """INSERT INTO data_plans(network,plan,provider_cost,selling_price,active) VALUES(:network,:plan,:cost,:price,:active)
        ON CONFLICT(network,plan) DO UPDATE SET provider_cost=:cost,selling_price=:price,active=:active,updated_at=CURRENT_TIMESTAMP
        RETURNING id,network,plan,provider_cost,selling_price,active,(selling_price-provider_cost) margin,updated_at""", {"network":network,"plan":plan,"cost":cost,"price":price,"active":1 if body.get("active", 1) else 0}).mappings().first()
    return {"success": True, "message": "Data plan saved successfully", "plan": dict(row)}


@router.patch("/api/admin/data-plans/{plan_id}")
def update_plan(request: Request, plan_id: int, body: dict):
    require_admin(request)
    with db_session() as db:
        current = q(db, "SELECT * FROM data_plans WHERE id=:id", {"id": plan_id}).mappings().first()
        if not current:
            raise HTTPException(404, "Data plan not found")
        cost = float(body.get("provider_cost", current["provider_cost"]))
        price = float(body.get("selling_price", current["selling_price"]))
        if cost < 0 or price <= 0 or price < cost:
            raise HTTPException(400, "Invalid pricing values")
        row = q(db, "UPDATE data_plans SET provider_cost=:cost,selling_price=:price,active=:active,updated_at=CURRENT_TIMESTAMP WHERE id=:id RETURNING id,network,plan,provider_cost,selling_price,active,(selling_price-provider_cost) margin,updated_at", {"cost":cost,"price":price,"active":int(body.get("active", current["active"])),"id":plan_id}).mappings().first()
    return {"success": True, "message": "Data plan updated successfully", "plan": dict(row)}
