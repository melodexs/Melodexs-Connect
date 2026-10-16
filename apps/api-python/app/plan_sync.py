"""Database-backed WiseSub catalog synchronization.

The provider currently documents package_code, package_name and price only.
Categories are therefore admin-assigned and unknown packages stay hidden;
POST /api/admin/data-plans/auto-categorize derives categories for
uncategorized plans without touching admin-set ones (see app/categorization.py).
"""
import asyncio
import json
import math
import re
from datetime import datetime, timezone

import httpx

from .config import settings, wisesub_base_url
from .database import db_session, engine, q
from .providers import wise_headers

NETWORK_NAMES = {"mtn": "MTN", "airtel": "Airtel", "glo": "Glo", "9mobile": "9mobile"}


def safe_error(exc: Exception) -> str:
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    detail = f"HTTP {status_code}" if status_code else "provider request or response could not be validated"
    return f"{type(exc).__name__}: {detail}"


def selling_price(cost: float) -> float:
    markup = float(settings.cheapdata_markup_percent)
    if not math.isfinite(markup) or markup < 0 or markup > 100:
        raise ValueError("CHEAPDATA_MARKUP_PERCENT must be between 0 and 100")
    price = float(math.ceil(cost * (1 + markup / 100)))
    if price > 1_000_000:
        raise ValueError("calculated selling price exceeds the supported limit")
    return price


def normalize_package(item: dict) -> dict:
    code = str(item.get("package_code") or "").strip()
    name = str(item.get("package_name") or "").strip()
    try:
        cost = float(item.get("price"))
    except (TypeError, ValueError):
        cost = float("nan")
    if not code or not name or not math.isfinite(cost) or cost <= 0 or cost > 1_000_000:
        raise ValueError("package must contain a stable package_code, package_name and valid price")
    clean = re.sub(r"^N[\d,]+\s*", "", name, flags=re.I).strip() or name
    size = re.search(r"(\d+(?:\.\d+)?\s*(?:KB|MB|GB|TB))", clean, re.I)
    validity = re.search(r"(\d+\s*(?:hours?|hrs?|days?|weeks?|months?|years?))", clean, re.I)
    return {"code": code, "name": name, "plan": clean, "cost": cost,
            "data_size": size.group(1) if size else None,
            "validity": validity.group(1) if validity else None}


async def fetch_network(client: httpx.AsyncClient, name: str, code: str) -> list[dict]:
    response = await client.get(f"{wisesub_base_url()}/packages",
        params={"service_type": "data", "provider_code": code}, headers=wise_headers(), follow_redirects=False)
    response.raise_for_status()
    result = response.json()
    packages = (result.get("data") or {}).get("packages") if result.get("success") is True else None
    if not isinstance(packages, list):
        raise ValueError(f"WiseSub returned an invalid package list for {name}")
    normalized = []
    for item in packages:
        if not isinstance(item, dict):
            raise ValueError(f"WiseSub returned a malformed package for {name}")
        normalized.append(normalize_package(item))
    # The live provider catalog has shipped distinct products that share a
    # package_code (seen on Glo: glo-dg-1485, glo-dg-1730). Purchases are made
    # by package_code, so exactly one catalog row may exist per code. Match
    # the legacy Node sync behavior: the last provider occurrence wins, and
    # the collision is reported instead of silently dropping a network.
    by_code: dict[str, dict] = {}
    duplicates: list[str] = []
    for item in normalized:
        if item["code"] in by_code:
            if item["code"] not in duplicates:
                duplicates.append(item["code"])
        by_code[item["code"]] = item
    return list(by_code.values()), duplicates


async def synchronize_plans() -> dict:
    # Discover known networks from the documented provider service catalog.
    # Do not infer new network names/codes from package labels.
    errors, results = [], []
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        try:
            response = await client.get(f"{wisesub_base_url()}/services", headers=wise_headers(), follow_redirects=False)
            response.raise_for_status()
            payload = response.json()
            services = (payload.get("data") or {}).get("data_bundles") if payload.get("success") is True else None
            if not isinstance(services, list):
                raise ValueError("WiseSub returned an invalid service catalog")
            discovered = {}
            for service in services:
                if not isinstance(service, dict) or service.get("type") != "data":
                    continue
                code = str(service.get("provider_code") or "").strip().lower()
                if code in NETWORK_NAMES:
                    discovered[code] = NETWORK_NAMES[code]
            if not discovered:
                raise ValueError("WiseSub service catalog contained no supported data networks")
        except Exception as exc:
            errors.append(f"service_catalog: {safe_error(exc)}")
            discovered = {}
        network_fetches = await asyncio.gather(
            *(fetch_network(client, name, code) for code, name in discovered.items()),
            return_exceptions=True,
        )
        for (code, name), fetched in zip(discovered.items(), network_fetches):
            if isinstance(fetched, Exception):
                errors.append(f"{name}: {safe_error(fetched)}")
            else:
                packages, duplicates = fetched
                if duplicates:
                    errors.append(f"{name}: duplicate provider package codes kept the last provider occurrence (provider catalog defect): {', '.join(duplicates)}")
                results.append((name, code, packages))

    added = updated = unavailable = 0
    with db_session() as db:
        run = q(db, "INSERT INTO data_plan_sync_runs(outcome) VALUES('running') RETURNING id").scalar()
        if engine.dialect.name == "postgresql":
            q(db, "SELECT pg_advisory_xact_lock(712034, 1)")
        # A failed network fetch never deactivates its previous catalog. Each
        # successful network snapshot is fully validated before its DB changes.
        for network, provider_code, packages in results:
            seen = {item["code"] for item in packages}
            existing = q(db, "SELECT id,provider_package_code FROM data_plans WHERE source='wisesub' AND provider_code=:code AND network=:network", {"code": provider_code, "network": network}).mappings().all()
            for row in existing:
                if row["provider_package_code"] and row["provider_package_code"] not in seen:
                    changed = q(db, "UPDATE data_plans SET provider_available=0,sync_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=:id AND provider_available<>0", {"id": row["id"]})
                    unavailable += max(changed.rowcount, 0)
            for item in packages:
                values = {**item, "network": network, "provider_code": provider_code,
                          "selling_price": selling_price(item["cost"])}
                current = q(db, "SELECT id FROM data_plans WHERE source='wisesub' AND provider_code=:provider_code AND provider_package_code=:code", {"provider_code": provider_code, "code": item["code"]}).first()
                if current:
                    occupied = q(db, "SELECT id FROM data_plans WHERE network=:network AND plan=:plan", {"network": network, "plan": item["plan"]}).first()
                    if occupied and occupied[0] != current[0]:
                        values["plan"] = f"{item['plan']} ({item['code']})"
                    q(db, """UPDATE data_plans SET plan=:plan,provider_cost=:cost,
                        selling_price=CASE WHEN selling_price_override IS NULL THEN :selling_price ELSE selling_price_override END,
                        provider_package_name=:name,data_size=:data_size,validity=:validity,
                        provider_available=1,provider='wisesub',source='wisesub',
                        last_synced_at=CURRENT_TIMESTAMP,sync_error=NULL,updated_at=CURRENT_TIMESTAMP
                        WHERE id=:id""", {**values, "id": current[0]})
                    updated += 1
                else:
                    # Preserve the existing (network, plan) key when a
                    # provider happens to reuse a human-readable name for a
                    # different package. The stable provider code remains the
                    # source of identity; the short suffix avoids a collision.
                    occupied = q(db, "SELECT id FROM data_plans WHERE network=:network AND plan=:plan", {"network": network, "plan": item["plan"]}).first()
                    if occupied:
                        values["plan"] = f"{item['plan']} ({item['code']})"
                    q(db, """INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,
                        provider,provider_code,provider_package_code,provider_package_name,data_size,
                        validity,source,last_synced_at,provider_available)
                        VALUES(:network,:plan,:cost,:selling_price,1,'wisesub',:provider_code,:code,
                        :name,:data_size,:validity,'wisesub',CURRENT_TIMESTAMP,1)""", values)
                    added += 1
        outcome = "success" if results and not errors else ("partial" if results else "failed")
        q(db, "UPDATE data_plan_sync_runs SET finished_at=CURRENT_TIMESTAMP,outcome=:outcome,added=:added,updated=:updated,unavailable=:unavailable,errors=:errors WHERE id=:id",
          {"outcome": outcome, "added": added, "updated": updated, "unavailable": unavailable,
           "errors": json.dumps(errors) if errors else None, "id": run})
    return {"success": not errors, "outcome": outcome, "added": added, "updated": updated,
            "unavailable": unavailable, "errors": errors}
