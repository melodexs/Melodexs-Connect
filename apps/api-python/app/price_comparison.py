"""Supplier price comparison for equivalent packages.

Read-only: comparing suppliers NEVER initiates a purchase and never
changes prices. The comparison:

- works on current supplier costs stored in data_plans (per provider
  source), never hard-coded prices;
- uses Decimal arithmetic for money;
- treats provider cost as the effective supplier cost (no provider in
  this integration documents per-transaction fees today; when one does,
  its adapter will expose the fee and it is included here);
- never routes to a provider that is disabled, unconfigured or unhealthy;
- never proposes selling prices below supplier cost;
- reports admin-pinned customer prices (selling_price_override) so the
  caller knows a customer price will not follow supplier changes.

Equivalence policy (app/package_matching.py): automatic routing requires
network + data allowance + validity + product family to be known and
equal. data_plans does not yet store provider family labels, so every
group is reported with eligible=False and a clear reason; the admin still
sees the supplier costs side by side. When family labels are added to the
catalog (per-provider plan_type column), groups become eligible without
any change to this module's callers.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from .database import db_session, q
from .package_matching import package_key, size_to_mb, validity_to_days


@dataclass(frozen=True)
class SupplierQuote:
    provider: str
    plan_id: int
    package_code: str
    plan_name: str
    supplier_cost: Decimal
    selling_price: Decimal
    price_override: Decimal | None
    available: bool


@dataclass
class ComparisonGroup:
    network: str
    data_size: str | None
    size_mb: Decimal | None
    validity_days: int | None
    family: str | None
    eligible: bool
    reason: str
    quotes: list[SupplierQuote] = field(default_factory=list)

    @property
    def cheapest_available(self) -> SupplierQuote | None:
        live = [quote for quote in self.quotes if quote.available]
        return min(live, key=lambda quote: quote.supplier_cost) if live else None

    def to_dict(self) -> dict:
        return {
            "network": self.network,
            "data_size": self.data_size,
            "size_mb": float(self.size_mb) if self.size_mb is not None else None,
            "validity_days": self.validity_days,
            "family": self.family,
            "eligible": self.eligible,
            "reason": self.reason,
            "cheapest_provider": self.cheapest_available.provider if self.cheapest_available else None,
            "quotes": [
                {"provider": quote.provider, "plan_id": quote.plan_id,
                 "package_code": quote.package_code, "plan_name": quote.plan_name,
                 "supplier_cost": float(quote.supplier_cost),
                 "selling_price": float(quote.selling_price),
                 "customer_price_override": float(quote.price_override) if quote.price_override is not None else None,
                 "available": quote.available}
                for quote in sorted(self.quotes, key=lambda x: (x.available, x.supplier_cost), reverse=True)],
        }


def compare_suppliers(network: str, eligible_provider_slugs: set[str]) -> list[ComparisonGroup]:
    """Compare all purchasable catalog rows of `network` across providers.

    eligible_provider_slugs: providers the caller (registry) considers
    routable (configured + enabled). Quotes from other providers are
    shown for transparency but marked available=False so they can never
    be selected by automatic routing.
    """
    groups: dict[tuple] = {}
    with db_session() as db:
        rows = q(db, """SELECT id, network, plan, data_size, validity, provider_cost,
                        selling_price, selling_price_override, provider_package_code,
                        source, active, provider_available
                        FROM data_plans
                        WHERE network=:network AND active=1 AND category IS NOT NULL
                          AND TRIM(category)<>'' AND source IS NOT NULL AND TRIM(source)<>''
                          AND provider_package_code IS NOT NULL
                        ORDER BY source, provider_cost, id""",
                 {"network": network}).mappings().all()
    for row in rows:
        size_mb = size_to_mb(row["data_size"])
        days = validity_to_days(row["validity"])
        # Automatic equivalence additionally requires a provider family
        # label, which data_plans does not store yet; see module docstring.
        equivalence_key = package_key(network=row["network"], data_size=row["data_size"],
                                      validity=row["validity"], plan_type=None)
        eligible = equivalence_key is not None
        group_key = (row["network"], size_mb, days)
        group = groups.setdefault(group_key, ComparisonGroup(
            network=row["network"], data_size=row["data_size"], size_mb=size_mb,
            validity_days=days, family=None, eligible=eligible,
            reason="" if eligible else
                   "Automatic routing disabled: the provider package family (SME/CG/gifting/standard) "
                   "is not stored for these plans, so equivalence cannot be confirmed"))
        supplier = str(row["source"]).strip().lower()
        cost = Decimal(str(row["provider_cost"]))
        price = Decimal(str(row["selling_price"]))
        available = (bool(row["active"]) and bool(row["provider_available"])
                     and supplier in eligible_provider_slugs
                     and cost <= price)
        group.quotes.append(SupplierQuote(
            provider=supplier, plan_id=int(row["id"]),
            package_code=str(row["provider_package_code"]),
            plan_name=str(row["plan"]),
            supplier_cost=cost,
            selling_price=price,
            price_override=(Decimal(str(row["selling_price_override"]))
                            if row["selling_price_override"] is not None else None),
            available=available))
    results = list(groups.values())
    for group in results:
        if not any(quote.available for quote in group.quotes):
            if not group.reason:
                group.reason = "No available supplier for this group"
    return results
