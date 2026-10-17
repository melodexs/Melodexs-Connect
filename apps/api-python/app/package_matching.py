"""Equivalence matching between provider packages.

Two packages from different providers are equivalent only when ALL of
the following are known and equal:

- network (MTN / Airtel / Glo / 9mobile, display form)
- data allowance, normalized to megabytes
- validity period, normalized to days
- product family (SME / corporate / gifting / standard)

A package whose data allowance, validity or family cannot be determined
is INELIGIBLE for automatic matching: uncertain matches must never be
auto-routed. This is stricter than the provider-facing catalog rules on
purpose; a wrong "equivalent" package delivers the wrong product to a
paying customer.

Family semantics: None (unknown family) never matches a known family,
and two different known families never match each other.
"""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class PackageKey:
    network: str
    size_mb: Decimal
    validity_days: int
    family: str | None

    def matches(self, other: "PackageKey") -> bool:
        if self.family is None or other.family is None:
            return False
        return (self.network == other.network
                and self.size_mb == other.size_mb
                and self.validity_days == other.validity_days
                and self.family == other.family)


def size_to_mb(data_size: str | None) -> Decimal | None:
    if not data_size:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)", str(data_size), re.I)
    if not match:
        return None
    try:
        value = Decimal(match.group(1))
    except InvalidOperation:
        return None
    unit = match.group(2).upper()
    factor = {"KB": Decimal("0.001"), "MB": Decimal("1"),
              "GB": Decimal("1024"), "TB": Decimal("1048576")}[unit]
    result = value * factor
    return result if result > 0 else None


def validity_to_days(validity: str | None) -> int | None:
    if not validity:
        return None
    text = str(validity).strip().lower()
    match = re.search(r"(\d+)\s*(day|days)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)\s*(week|weeks)", text)
    if match:
        return int(match.group(1)) * 7
    match = re.search(r"(\d+)\s*(month|months)", text)
    if match:
        return int(match.group(1)) * 30
    match = re.search(r"(\d+)\s*(hour|hours|hrs?)", text)
    if match:
        # Sub-day validity: keep it distinct from 1-day packages.
        return 1
    if "daily" in text:
        return 1
    if "weekly" in text:
        return 7
    if "monthly" in text:
        return 30
    return None


def normalize_family(plan_type: str | None) -> str | None:
    """Normalize a provider's product family label.

    Unknown labels are preserved as-is but lowercased; None stays None
    (never guessed). Only providers' own labels are trusted.
    """
    if plan_type is None:
        return None
    text = str(plan_type).strip().lower()
    if not text:
        return None
    aliases = {"corporate gifting": "corporate", "cg": "corporate",
               "sme": "sme", "gifting": "gifting", "gift": "gifting",
               "standard": "standard", "normal": "standard"}
    return aliases.get(text, text)


def package_key(*, network: str, data_size: str | None, validity: str | None,
                plan_type: str | None) -> PackageKey | None:
    """Build a match key, or None when the package is ineligible for
    automatic equivalence matching (unknown size, validity or family)."""
    size_mb = size_to_mb(data_size)
    days = validity_to_days(validity)
    family = normalize_family(plan_type)
    if size_mb is None or days is None or family is None:
        return None
    network_clean = {"mtn": "MTN", "airtel": "Airtel", "glo": "Glo",
                     "9mobile": "9mobile"}.get(str(network or "").strip().lower())
    if network_clean is None:
        return None
    return PackageKey(network=network_clean, size_mb=size_mb,
                      validity_days=days, family=family)
