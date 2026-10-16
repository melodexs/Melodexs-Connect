"""Tests for app.categorization and the categorized catalog endpoints.

The fixture cases are real WiseSub live-catalog packages (2026-10-16 catalog)
so the rules are pinned against actual provider naming, not guesses.
"""
import secrets

from fastapi.testclient import TestClient

from app import main
from app.categorization import CAMPUS, DAILY, MEGA, MONTHLY, NIGHT, ROUTER, SOCIAL, WEEKLY, categorize, category_sort_sql
from app.database import db_session, q


def test_known_live_packages_map_to_expected_categories():
    cases = [
        # Social / YouTube first products (incl. add-on exclusion cases)
        ("mtn-500mb-500", "500MB + 1GB YouTube (7 Days) - N500", SOCIAL),
        ("mtn-1gb-600", "N800 1GB + 1GB YouTube Night + 100MB YouTube Music - Weekly", SOCIAL),
        ("glo-social-oneoff-300", "Glo MyG N300 1 GB 3 Days OneOff (Whatsapp, Instagram, Snapchat, Boomplay, Audiomac, GloTV, Tiktok)", SOCIAL),
        ("glo-tv-1400", "Glo TV VOD 6GB 30days", SOCIAL),
        ("glo-special-500-15days", "1.8GB 15 Days - Social Bundles N500", SOCIAL),
        ("airt-100", "200MB Social Plan (2 Days) - 100 Naira - 1Day", SOCIAL),
        ("airt-social-500-7", "1.5GB Social Plan - 500 Naira", SOCIAL),
        ("glo-youtube-250", "1GB 1 Day - Youtube Special N250", SOCIAL),
        # ...but a Youtube & Social suffix is an add-on, not the product
        ("airt-1500-30", "2GB Monthly Plan + Youtube & Social Plan (30 Days)- 2,000 Naira", MONTHLY),
        ("airt-1000-7", "1.5GB Weekly Plan + Youtube & Social Plans (7 Days) - 1,000 Naira", WEEKLY),
        # Night & Binge
        ("airt-50", "250MB Night Plan (12 - 5 AM) - 50 Naira  - 1Day", NIGHT),
        ("airt-binge-500-1", "500 Naira Binge Plan 1GB", NIGHT),
        ("airt-1000-2", "1,000 Naira - 4GB Plan + 2GB YouTube Night + 200MB YT/IG/TT(2 Days)", NIGHT),
        ("glo-night-60-1day", "350MB Night - N60", NIGHT),
        # ...but a "(Best Value) ... Night plan" Glo budget package is a duration plan
        ("glo-dg-350", "1GB (Best Value) - 366 Naira - 14 days Night plan", MONTHLY),
        ("glo-2days-200", "250MB + 25MB Night - N200 - 2 Days", WEEKLY),
        # Campus Booster
        ("glo-campus-booster-1000", "2.2GB + 2GB Night - N1000 - 30 Days - Camp-Boost", CAMPUS),
        # Router & MiFi
        ("airt-mifi-20000-30", "100GB Unlimited Uiltra 20 - Router Only (30 Days) - 20,000 Naira", ROUTER),
        ("mtn-hynetflex-14500-30", "60GB Monthly Broadband Plan - N14,500", ROUTER),
        ("mtn-1500gb-yearly", "MTN 1.5TB - N225,000 Broadband Router", ROUTER),
        # Mega & Long-Term
        ("glo-mega-50000", "310GB 60 Days - Mega N50000", MEGA),
        ("mtn-480gb-90000", "480GB 3-Month Plan - N90,000", MEGA),
        ("airt-100000", "680GB Data (365 Days) - 100,000 Naira", MEGA),
        ("airt-50000", "200GB Monthly Plan (90 Days) - 50,000 Naira", MEGA),
        # Duration buckets
        ("mtn-10mb-100", "110MB Daily Plan (1 Day) - N100", DAILY),
        ("airt-daily-100", "Airtel Data - 100 Naira - 110MB - 1 Day", DAILY),
        ("mtn-2-5gb-900", "MTN N900 2.5GB - 2 days", WEEKLY),
        ("mtn-1500mb-1000", "1.5GB Weekly Plan (7 Days) - N1,000", WEEKLY),
        ("mtn-12gb-7d-4500", "12.5GB  14 days - N4,500", MONTHLY),
        ("mtn-3.5gb-2500", "MTN N,2500 3.5GB +5mins Monthly Plan", MONTHLY),
        ("mtn-260gb-monthly", "MTN 260GB + 2GB daily upon exhausting main bundle - N45,000", MONTHLY),
        ("glo-always-on-2000", "6.1GB (410MB per day) 15 Days - Always On N2000", MONTHLY),
        ("glo-sunday-200", "875MB 1 Day - Weekend N200", DAILY),
        ("airt-200", "230MB Daily Plan (2 Days) - 200 Naira - 200MB - 1Day", WEEKLY),
        ("eti-500", "T2 650MB - 500 Naira - 3 days", WEEKLY),
        ("t2-250mb-200", "T2 N200 - 250MB Anytime Data Plan (7 Days)", WEEKLY),
        ("eti-1000", "9mobile 2GB - 1,000 Naira - 30 Days", MONTHLY),
    ]
    for code, name, expected in cases:
        assert categorize(code, name) == expected, (code, name, expected)


def test_unknown_packages_stay_uncategorized():
    assert categorize("", "name") is None
    assert categorize("x", "") is None
    assert categorize("mystery-1", "Strange product") is None
    assert categorize(None, None) is None


def test_category_sort_sql_places_buyer_order_first():
    sql = category_sort_sql()
    assert "'daily plans' THEN 1" in sql
    assert "'router & mifi' THEN 7" in sql
    assert sql.endswith("ELSE 99 END, LOWER(category)")


def _register_and_promote(client, label):
    suffix = secrets.token_hex(4)
    response = client.post("/api/register", json={
        "name": f"Cat Admin {label}", "email": f"catadmin-{label}-{suffix}@example.com",
        "phone": f"086{int(suffix, 16) % 10**8:08d}", "password": "password123"})
    user_id = response.json()["user"]["id"]
    with db_session() as db:
        q(db, "UPDATE users SET is_admin=1 WHERE id=:id", {"id": user_id})
    return user_id, suffix


def _insert_uncategorized_plan(suffix, name="300MB Night Plan - 250 Naira - 1 day"):
    with db_session() as db:
        return q(db, """INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,
            provider,provider_code,provider_package_code,provider_package_name,source,provider_available)
            VALUES('MTN',:plan,100,102,1,'wisesub','mtn',:code,:name,'wisesub',1) RETURNING id""",
            {"plan": f"Cat plan {suffix}", "code": f"mtn-cat-{suffix}", "name": name}).scalar()


def test_auto_categorize_requires_admin_and_never_overwrites_admin_labels():
    suffix = secrets.token_hex(5)
    plan_id = _insert_uncategorized_plan(suffix)
    with TestClient(main.app) as client:
        # Non-admin users are rejected by the admin gate.
        client.post("/api/register", json={"name": "Plain User", "email": f"plain-{suffix}@example.com",
            "phone": f"087{int(suffix, 16) % 10**8:08d}", "password": "password123"})
        assert client.post("/api/admin/data-plans/auto-categorize").status_code == 403
        _register_and_promote(client, "a")
        first = client.post("/api/admin/data-plans/auto-categorize")
        assert first.status_code == 200
        body = first.json()
        assert body["success"] is True
        assert body["categorized"] >= 1
        assert "Night & Binge" in body["by_category"]
        with db_session() as db:
            assert q(db, "SELECT category FROM data_plans WHERE id=:id", {"id": plan_id}).scalar() == "Night & Binge"
        # An admin-set label is never overwritten by a later run.
        with db_session() as db:
            q(db, "UPDATE data_plans SET category='Owner Label' WHERE id=:id", {"id": plan_id})
        second = client.post("/api/admin/data-plans/auto-categorize").json()
        assert second["success"] is True
        with db_session() as db:
            assert q(db, "SELECT category FROM data_plans WHERE id=:id", {"id": plan_id}).scalar() == "Owner Label"
    with db_session() as db:
        q(db, "DELETE FROM data_plans WHERE id=:id", {"id": plan_id})


def test_data_categories_endpoint_orders_buyer_friendly():
    suffix = secrets.token_hex(5)
    inserted = []
    with db_session() as db:
        for category in ("Weekly Plans", "Daily Plans", "Social & YouTube"):
            inserted.append(q(db, """INSERT INTO data_plans(network,plan,provider_cost,selling_price,active,category,
                provider,provider_code,provider_package_code,provider_package_name,source,provider_available)
                VALUES('MTN',:plan,100,102,1,:category,'wisesub','mtn',:code,:name,'wisesub',1) RETURNING id""",
                {"plan": f"Cat order {category} {suffix}", "category": category,
                 "code": f"mtn-ord-{suffix}-{category[:3]}", "name": f"Cat order {category}"}).scalar())
    try:
        with TestClient(main.app) as client:
            response = client.get("/api/data-categories?network=MTN")
            assert response.status_code == 200
            names = [c["category"] for c in response.json()["categories"]]
            assert names.index("Daily Plans") < names.index("Weekly Plans")
            assert "Social & YouTube" in names
    finally:
        with db_session() as db:
            for plan_id in inserted:
                q(db, "DELETE FROM data_plans WHERE id=:id", {"id": plan_id})
