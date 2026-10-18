"""Deterministic catalog categorization for WiseSub data plans.

WiseSub's partner API documents only package_code, package_name and price
(no category field), so the customer-facing category is derived from the
provider's own package naming conventions:

- Router & MiFi    : hardware-bound plans (mifi/router/hynetflex/broadband)
- Social & YouTube: social-first, YouTube-first and Glo TV streaming plans
- Night & Binge   : night-only and binge plans
- Campus Booster  : Glo campus booster family
- Mega & Long-Term: mega plans and 2-month/3-month/90/120/365-day volumes
- Daily Plans     : validity of 1-2 days
- Weekly Plans    : validity of 3-7 days
- Monthly Plans   : validity of 8-30 days (includes 14-day plans)

Rules are evaluated in order and only ever assign a category; a package
that matches nothing returns None so it stays hidden until an admin
reviews it. Admin-set categories are never overwritten by this module.
"""
import re

DAILY = "Daily Plans"
WEEKLY = "Weekly Plans"
MONTHLY = "Monthly Plans"
SOCIAL = "Social & YouTube"
NIGHT = "Night & Binge"
CAMPUS = "Campus Booster"
ROUTER = "Router & MiFi"
MEGA = "Mega & Long-Term"

# Buyer-facing ordering for the category step (used by /api/data-categories).
CATEGORY_ORDER = [DAILY, WEEKLY, MONTHLY, SOCIAL, NIGHT, CAMPUS, ROUTER, MEGA]

# WiseSub sells YouTube-first bundles whose package codes do not carry a
# social/youtube marker (MTN "500MB + 1GB YouTube", "1GB + 1GB YouTube
# Night + 100MB YouTube Music"). They are pinned explicitly; if WiseSub
# introduces new such codes they still fall through to duration buckets.
_KNOWN_YOUTUBE_CODES = {"mtn-500mb-500", "mtn-1gb-600"}

# Airtel's "Binge Plan" family: two members carry no binge marker in their
# name ("1,000 Naira - 4GB Plan + 2GB YouTube Night + 200MB YT/IG/TT").
_KNOWN_BINGE_CODES = {"airt-600", "airt-750-2", "airt-1000-2", "airt-1500-2"}


def _validity_days(name: str, code: str):
    match = re.search(r"(\d+)\s*(?:days?|hrs?|hours?)\b", name)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)\s*weeks?\b", name)
    if match:
        return int(match.group(1)) * 7
    match = re.search(r"(\d+)\s*months?\b", name)
    if match:
        return int(match.group(1)) * 30
    for keyword, days in (("monthly", 30), ("weekly", 7), ("daily", 1)):
        if keyword in code or keyword in name:
            return days
    return None


def categorize(package_code: str | None, package_name: str | None) -> str | None:
    """Return the customer-facing category for a WiseSub package.

    Returns None when the package matches no rule; such plans stay
    category-less (hidden from the catalog) until an admin assigns one.
    """
    code = str(package_code or "").strip().lower()
    name = str(package_name or "").strip().lower()
    if not code or not name:
        return None

    # Hardware-bound plans first: they override duration naming.
    if (
        any(marker in code for marker in ("mifi", "router", "hynetflex", "broadband"))
        or "router only" in name
        or "5g router" in name
        or "5g broadband" in name
        or "broadband router" in name
    ):
        return ROUTER

    # Social/YouTube/streaming-first products. A "+ Youtube & Social" suffix
    # on a regular duration plan is an add-on, not the product itself.
    if (
        any(marker in code for marker in ("social", "youtube", "myg"))
        or code.startswith("glo-tv")
        or code in _KNOWN_YOUTUBE_CODES
        or "social bundles" in name
        or ("social plan" in name and " + " not in name)
        or "youtube special" in name
    ):
        return SOCIAL

    # Night-only and binge plans. "(Best Value) ... Night plan" Glo packages
    # are budget duration plans, not night-only products.
    if (
        any(marker in code for marker in ("night", "binge"))
        or code in _KNOWN_BINGE_CODES
        or ("night plan" in name and "best value" not in name)
        or "binge plan" in name
    ):
        return NIGHT

    if "campus" in code or "camp-boost" in name:
        return CAMPUS

    # Mega volumes and long-horizon plans (60+ days).
    if (
        "mega" in code
        or "yearly" in code
        or any(marker in name for marker in ("2-month", "3-month", " 60 days", " 90 days", " 120 days", " 365 days"))
    ):
        return MEGA

    days = _validity_days(name, code)
    if days is None:
        return None
    # Two-day packs are short-lived budget buys shown next to daily packs;
    # Weekly starts at 3 days. (WiseSub sells both 1-day and 2-day variants
    # of the same "Daily Plan" product line.)
    if days <= 2:
        return DAILY
    if days <= 7:
        return WEEKLY
    if days <= 30:
        return MONTHLY
    return MEGA


def category_sort_sql(column: str = "LOWER(TRIM(category))") -> str:
    """SQL ORDER BY fragment placing known categories in buyer order."""
    cases = []
    for index, label in enumerate(CATEGORY_ORDER, start=1):
        cases.append(f"WHEN '{label.lower()}' THEN {index}")
    return f"CASE {column} {' '.join(cases)} ELSE 99 END, LOWER(category)"
