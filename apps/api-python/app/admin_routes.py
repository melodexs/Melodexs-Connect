import re
import math
from fastapi import APIRouter, Request, HTTPException
from .database import db_session, q
from .security import require_admin
from .categorization import categorize, CATEGORY_ORDER
from .price_comparison import compare_suppliers
from .provider_registry import (all_adapters, get_adapter, provider_enabled,
                                record_health, routing_status)
from .plan_sync import synchronize_plans
from .providers import wise_status
from .database import engine
from .config import settings

router = APIRouter()


@router.get("/api/admin/data-plans")
def list_plans(request: Request):
    require_admin(request)
    with db_session() as db:
        rows = q(db, "SELECT id,network,plan,provider_cost,selling_price,selling_price_override,(selling_price-provider_cost) margin,active,provider_available,category,provider_category,sync_error,provider,provider_code,provider_package_code,provider_package_name,data_size,validity,source,last_synced_at,created_at,updated_at FROM data_plans WHERE source IS NOT NULL AND TRIM(source)<>'' ORDER BY CASE network WHEN 'MTN' THEN 1 WHEN 'Airtel' THEN 2 WHEN 'Glo' THEN 3 WHEN '9mobile' THEN 4 ELSE 5 END,selling_price,id").mappings().all()
    return {"success": True, "plans": [dict(row) for row in rows]}


@router.post("/api/admin/data-plans/synchronize")
async def sync_plans(request: Request):
    require_admin(request)
    try:
        result = await synchronize_plans()
    except Exception as exc:
        raise HTTPException(502, "Plan synchronization failed safely. Existing plans were preserved.") from exc
    return result


@router.post("/api/admin/data-plans/auto-categorize")
def auto_categorize(request: Request):
    """Assign derived categories to uncategorized WiseSub plans.

    Only plans with no category are touched; admin-set categories are never
    overwritten. Plans that match no rule stay hidden for manual review.
    """
    require_admin(request)
    assigned: dict[str, int] = {label: 0 for label in CATEGORY_ORDER}
    remaining = 0
    with db_session() as db:
        rows = q(db, "SELECT id,provider_package_code,provider_package_name FROM data_plans WHERE LOWER(TRIM(source))='wisesub' AND (category IS NULL OR TRIM(category)='')").mappings().all()
        for row in rows:
            category = categorize(row["provider_package_code"], row["provider_package_name"])
            if category is None:
                remaining += 1
                continue
            q(db, "UPDATE data_plans SET category=:category,updated_at=CURRENT_TIMESTAMP WHERE id=:id AND (category IS NULL OR TRIM(category)='')",
              {"category": category, "id": row["id"]})
            assigned[category] += 1
    return {"success": True, "categorized": sum(assigned.values()),
            "remaining_uncategorized": remaining,
            "by_category": {k: v for k, v in assigned.items() if v}}


@router.get("/api/admin/data-plans/synchronization")
def sync_status(request: Request):
    require_admin(request)
    with db_session() as db:
        latest = q(db, "SELECT id,started_at,finished_at,outcome,added,updated,unavailable,errors FROM data_plan_sync_runs ORDER BY id DESC LIMIT 1").mappings().first()
    return {"success": True, "sync": dict(latest) if latest else None}


@router.get("/api/admin/purchases/pending")
def pending_purchases(request: Request):
    require_admin(request)
    with db_session() as db:
        rows = q(db, "SELECT t.id,t.user_id,u.email,t.amount,t.status,t.reference,t.provider_reference,t.provider,t.description,t.created_at FROM transactions t JOIN users u ON u.id=t.user_id WHERE t.type='debit' AND t.status='pending' ORDER BY t.id ASC LIMIT 200").mappings().all()
    return {"success": True, "transactions": [dict(row) for row in rows]}


@router.post("/api/admin/purchases/reconcile")
async def reconcile_purchases(request: Request):
    require_admin(request)
    with db_session() as db:
        pending = q(db, "SELECT id,user_id,reference,provider_reference,provider FROM transactions WHERE type='debit' AND status='pending' ORDER BY id ASC LIMIT 100").mappings().all()
    results = []
    for transaction in pending:
        reference = transaction["provider_reference"] or transaction["reference"]
        provider_slug = str(transaction["provider"] or "wisesub").strip().lower()
        failure_is_final = False
        try:
            if provider_slug == "wisesub":
                response = await wise_status(reference)
                payload = response.json()
                status = ((payload.get("data") or {}).get("status") or "").strip().lower() if response.status_code < 400 and payload.get("success") is True else ""
            else:
                adapter = get_adapter(provider_slug)
                if adapter is None or not adapter.is_configured():
                    results.append({"reference": transaction["reference"], "status": "unresolved", "detail": f"Provider '{provider_slug}' is not configured for reconciliation"})
                    continue
                outcome = await adapter.transaction_status(reference)
                status = outcome.status if outcome.recognized else ""
                # A provider's "failed" is only final when it documents
                # automatic refunds; anything else needs admin review.
                failure_is_final = adapter.failure_status_is_final and adapter.auto_refunds_on_failure
            if status not in {"successful", "failed", "pending"}:
                results.append({"reference": transaction["reference"], "status": "unresolved", "detail": "Provider response was not a recognized final status"})
                continue
            if status == "pending":
                results.append({"reference": transaction["reference"], "status": "pending"})
                continue
            if status == "failed" and not (failure_is_final or settings.wisesub_failure_status_confirmed):
                results.append({"reference": transaction["reference"], "status": "failed_needs_admin_review"})
                continue
            with db_session() as db:
                sql = "SELECT user_id,amount,status,description FROM transactions WHERE id=:id"
                if engine.dialect.name != "sqlite": sql += " FOR UPDATE"
                current = q(db, sql, {"id": transaction["id"]}).mappings().first()
                if not current or current["status"] != "pending":
                    results.append({"reference": transaction["reference"], "status": "already_processed"})
                    continue
                if status == "successful":
                    q(db, "UPDATE transactions SET status='successful',provider_reference=:provider_reference,description=:description WHERE id=:id AND status='pending'", {"provider_reference": reference, "description": current["description"] + " | WiseSub status confirmed successful", "id": transaction["id"]})
                else:
                    changed = q(db, "UPDATE transactions SET status='failed',description=:description WHERE id=:id AND status='pending'", {"description": current["description"] + " | WiseSub status confirmed failed; wallet refund issued", "id": transaction["id"]})
                    if changed.rowcount == 1:
                        q(db, "UPDATE users SET balance=balance+:amount WHERE id=:id", {"amount": current["amount"], "id": current["user_id"]})
            results.append({"reference": transaction["reference"], "status": status})
        except Exception as exc:
            results.append({"reference": transaction["reference"], "status": "unresolved", "detail": type(exc).__name__})
    return {"success": True, "checked": len(results), "results": results}


@router.post("/api/admin/purchases/{transaction_id}/resolve")
def resolve_pending_purchase(request: Request, transaction_id: int, body: dict):
    admin_id = require_admin(request)
    status = str(body.get("status") or "").lower()
    if status not in {"successful", "failed"}:
        raise HTTPException(400, "Status must be successful or failed")
    resolve_pending_purchase_state(transaction_id, status, admin_id)
    return {"success": True, "message": f"Pending purchase marked {status}"}


def resolve_pending_purchase_state(transaction_id: int, status: str, admin_id: int):
    with db_session() as db:
        sql = "SELECT user_id,amount,status,description FROM transactions WHERE id=:id AND type='debit'"
        if engine.dialect.name != "sqlite": sql += " FOR UPDATE"
        current = q(db, sql, {"id": transaction_id}).mappings().first()
        if not current:
            raise HTTPException(404, "Purchase transaction not found")
        if current["status"] != "pending":
            raise HTTPException(409, "Only pending purchases can be resolved")
        description = current["description"] + f" | Resolved {status} by admin {admin_id}"
        if status == "failed":
            changed = q(db, "UPDATE transactions SET status='failed',description=:description WHERE id=:id AND status='pending'", {"description": description, "id": transaction_id})
            if changed.rowcount == 1:
                q(db, "UPDATE users SET balance=balance+:amount WHERE id=:id", {"amount": current["amount"], "id": current["user_id"]})
        else:
            q(db, "UPDATE transactions SET status='successful',description=:description WHERE id=:id AND status='pending'", {"description": description, "id": transaction_id})
    return True


@router.post("/api/admin/data-plans")
def create_plan(request: Request, body: dict):
    require_admin(request)
    network, plan = str(body.get("network") or "").strip(), str(body.get("plan") or "").strip().upper()
    if network not in {"MTN", "Airtel", "Glo", "9mobile"}:
        raise HTTPException(400, "Invalid network")
    if not re.fullmatch(r"\d+(?:\.\d+)?(?:MB|GB)", plan, re.I):
        raise HTTPException(400, "Invalid plan format. Example: 1GB or 500MB")
    try:
        cost = float(body.get("provider_cost"))
    except (TypeError, ValueError):
        cost = float("nan")
    if not (math.isfinite(cost) and 0 <= cost <= 1_000_000):
        raise HTTPException(400, "Provider cost must be 0 or greater")
    try:
        price = float(body.get("selling_price"))
    except (TypeError, ValueError):
        price = float("nan")
    if not (math.isfinite(price) and 0 < price <= 1_000_000):
        raise HTTPException(400, "Selling price must be greater than 0")
    if price < cost:
        raise HTTPException(400, "Selling price cannot be below provider cost")
    try:
        active = int(float(body.get("active", 1)) != 0)
    except (TypeError, ValueError):
        active = 0
    with db_session() as db:
        row = q(db, """INSERT INTO data_plans(network,plan,provider_cost,selling_price,selling_price_override,active) VALUES(:network,:plan,:cost,:price,:price,:active)
        ON CONFLICT(network,plan) DO UPDATE SET provider_cost=:cost,selling_price=:price,active=:active,updated_at=CURRENT_TIMESTAMP
        RETURNING id,network,plan,provider_cost,selling_price,active,(selling_price-provider_cost) margin,updated_at""", {"network":network,"plan":plan,"cost":cost,"price":price,"active":active}).mappings().first()
    return {"success": True, "message": "Data plan saved successfully", "plan": dict(row)}


@router.patch("/api/admin/data-plans/{plan_id}")
def update_plan(request: Request, plan_id: str, body: dict):
    require_admin(request)
    try:
        plan_id = int(plan_id)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid plan ID")
    if plan_id <= 0:
        raise HTTPException(400, "Invalid plan ID")
    with db_session() as db:
        current = q(db, "SELECT * FROM data_plans WHERE id=:id", {"id": plan_id}).mappings().first()
        if not current:
            raise HTTPException(404, "Data plan not found")
        cost = current["provider_cost"]
        if "provider_cost" in body:
            try: cost = float(body["provider_cost"])
            except (TypeError, ValueError): raise HTTPException(400, "Invalid provider cost")
            if not (0 <= cost <= 1_000_000): raise HTTPException(400, "Invalid provider cost")
        override = current["selling_price_override"]
        price = current["selling_price"]
        if "selling_price" in body:
            raw = body["selling_price"]
            if raw is None:
                override = None
                from .plan_sync import selling_price
                price = selling_price(float(cost))
            else:
                try: price = float(raw)
                except (TypeError, ValueError): raise HTTPException(400, "Invalid selling price")
                if not (0 < price <= 1_000_000) or price < float(cost): raise HTTPException(400, "Selling price must be positive, within limits, and no lower than provider cost")
                override = price
        category = current["category"]
        if "category" in body:
            raw = body["category"]
            if raw is None or str(raw).strip() == "": category = None
            elif len(str(raw).strip()) > 80: raise HTTPException(400, "Category must be 80 characters or fewer")
            else: category = str(raw).strip()
        try:
            active = int(float(body.get("active", current["active"])) != 0)
        except (TypeError, ValueError):
            active = 0
        row = q(db, "UPDATE data_plans SET provider_cost=:cost,selling_price=:price,selling_price_override=:override,category=:category,active=:active,updated_at=CURRENT_TIMESTAMP WHERE id=:id RETURNING id,network,plan,provider_cost,selling_price,selling_price_override,category,active,provider_available,(selling_price-provider_cost) margin,updated_at", {"cost":cost,"price":price,"override":override,"category":category,"active":active,"id":plan_id}).mappings().first()
    return {"success": True, "message": "Data plan updated successfully", "plan": dict(row)}

# ---------------------------------------------------------------------------
# Multi-provider fulfillment platform (admin only)
# ---------------------------------------------------------------------------

@router.get("/api/admin/providers")
def list_providers(request: Request):
    require_admin(request)
    with db_session() as db:
        rows = {r["slug"]: dict(r) for r in q(db, "SELECT slug,name,enabled,status,last_check_at,last_check_detail FROM providers").mappings().all()}
    providers = []
    for adapter in all_adapters():
        row = rows.get(adapter.slug, {})
        providers.append({
            "slug": adapter.slug,
            "name": adapter.display_name,
            "configured": adapter.is_configured(),
            "enabled": bool(row.get("enabled", 0)),
            "health": row.get("status"),
            "last_check_at": row.get("last_check_at"),
            "last_check_detail": row.get("last_check_detail"),
            "auto_refunds_on_failure": adapter.auto_refunds_on_failure,
            "capabilities": list(adapter.capabilities),
        })
    return {"success": True, "providers": providers, "routing": routing_status()}


@router.patch("/api/admin/providers/{slug}")
def set_provider_enabled(request: Request, slug: str, body: dict):
    require_admin(request)
    slug = slug.strip().lower()
    adapter = get_adapter(slug)
    if adapter is None:
        raise HTTPException(404, "Unknown provider")
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(400, "enabled must be true or false")
    if slug == "wisesub" and not enabled:
        # WiseSub is the active fulfillment provider; disabling it while
        # routing is WiseSub-only would break every purchase.
        raise HTTPException(409, "WiseSub cannot be disabled while it is the active fulfillment provider")
    if enabled and not adapter.is_configured():
        raise HTTPException(409, "This provider has no credentials configured yet")
    with db_session() as db:
        changed = q(db, "UPDATE providers SET enabled=:enabled,updated_at=CURRENT_TIMESTAMP WHERE slug=:slug AND enabled<>:enabled", {"enabled": 1 if enabled else 0, "slug": slug})
        if changed.rowcount == 0:
            row = q(db, "SELECT enabled FROM providers WHERE slug=:slug", {"slug": slug}).scalar()
            if row is None:
                q(db, "INSERT INTO providers(slug,name,enabled,updated_at) VALUES(:slug,:name,:enabled,CURRENT_TIMESTAMP)", {"slug": slug, "name": adapter.display_name, "enabled": 1 if enabled else 0})
    return {"success": True, "slug": slug, "enabled": enabled}


@router.post("/api/admin/providers/{slug}/health-check")
async def provider_health_check(request: Request, slug: str):
    require_admin(request)
    slug = slug.strip().lower()
    adapter = get_adapter(slug)
    if adapter is None:
        raise HTTPException(404, "Unknown provider")
    if not adapter.is_configured():
        return {"success": True, "slug": slug, "supported": False,
                "detail": "No credentials configured for this provider"}
    result = await adapter.health_check()
    if result.supported and result.message == "ok":
        record_health(slug, True, "ok", str(result.balance))
    else:
        record_health(slug, False, result.message or "check failed")
    return {"success": True, "slug": slug, "supported": result.supported,
            "balance": float(result.balance) if result.balance is not None else None,
            "currency": result.currency, "detail": result.message}


@router.get("/api/admin/providers/price-comparison")
def provider_price_comparison(request: Request, network: str):
    require_admin(request)
    if network not in {"MTN", "Airtel", "Glo", "9mobile"}:
        raise HTTPException(400, "Invalid network")
    from .provider_registry import eligible_provider_slugs
    groups = compare_suppliers(network, eligible_provider_slugs())
    return {"success": True, "network": network,
            "routing": routing_status(),
            "groups": [group.to_dict() for group in groups]}
