"""Provider registry: configuration, enablement and health for adapters.

The registry is the single place that decides which providers exist and
which are eligible for fulfillment:

- A provider is CONFIGURED when its credentials exist in settings.
- A provider is ENABLED when the providers table row says so (admin
  decision). WiseSub ships enabled; every other provider ships disabled.
- A provider is ELIGIBLE when configured + enabled (+ healthy when a
  health check has run).

Fulfillment routing stays WiseSub-only until MULTI_PROVIDER_ROUTING_ENABLED
is true AND another provider is configured and enabled. The purchase
path consults resolve_fulfillment_provider(), which never returns an
unconfigured or disabled adapter.
"""
from datetime import datetime, timezone

from .config import settings
from .database import db_session, q
from .provider_base import ProviderAdapter
from .provider_isquaredata import IsquareDataAdapter
from .provider_meledata import MeleDataAdapter
from .provider_rizpay import RizPayAdapter
from .provider_wisesub import WiseSubAdapter

# The primary fulfillment provider is configuration-driven: WiseSub is the
# safe code default; production activates ISQUAREDATA via
# ACTIVE_CATALOG_SOURCE. WiseSub always stays registered, enabled and
# reconcilable (it is never removed).
_RETAINED_PROVIDER = "wisesub"


def primary_provider() -> str:
    source = (getattr(settings, "active_catalog_source", "") or "").strip().lower()
    if source not in _ADAPTERS or _ADAPTERS[source].selection_excluded:
        return _RETAINED_PROVIDER
    return source


def default_adapters() -> list[ProviderAdapter]:
    return [WiseSubAdapter(), IsquareDataAdapter(), MeleDataAdapter(),
            RizPayAdapter()]


_ADAPTERS: dict[str, ProviderAdapter] = {a.slug: a for a in default_adapters()}


def get_adapter(slug: str) -> ProviderAdapter | None:
    return _ADAPTERS.get(slug)


def all_adapters() -> list[ProviderAdapter]:
    return list(_ADAPTERS.values())


def ensure_provider_rows() -> None:
    """Register known providers in the DB with safe defaults (idempotent).

    WiseSub is enabled; every additional provider starts DISABLED and
    stays disabled until an admin enables it after credentials are set.
    """
    with db_session() as db:
        for adapter in all_adapters():
            default_enabled = 1 if adapter.slug in (primary_provider(), _RETAINED_PROVIDER) else 0
            q(db, """INSERT INTO providers(slug, name, enabled, updated_at)
                     VALUES(:slug, :name, :enabled, CURRENT_TIMESTAMP)
                     ON CONFLICT(slug) DO NOTHING""",
              {"slug": adapter.slug, "name": adapter.display_name, "enabled": default_enabled})
        # The primary provider can never be disabled while it is the only
        # enabled one; keep its row enabled even if the table was created
        # with a different default.
        q(db, "UPDATE providers SET enabled=1 WHERE slug IN (:active, :retained)", {"active": primary_provider(), "retained": _RETAINED_PROVIDER})


def provider_enabled(slug: str) -> bool:
    with db_session() as db:
        row = q(db, "SELECT enabled FROM providers WHERE slug=:slug", {"slug": slug}).scalar()
    return bool(row)


def eligible_provider_slugs() -> set[str]:
    """Configured + enabled provider slugs.

    Selection-excluded providers (retired alternatives kept only for
    compatibility) are never eligible for fulfillment or fallback."""
    result = set()
    for adapter in all_adapters():
        if adapter.selection_excluded:
            continue
        if adapter.is_configured() and provider_enabled(adapter.slug):
            result.add(adapter.slug)
    return result


def record_health(slug: str, supported: bool, detail: str, balance=None) -> None:
    with db_session() as db:
        q(db, """UPDATE providers
                 SET status=:status, last_check_at=CURRENT_TIMESTAMP, last_check_detail=:detail
                 WHERE slug=:slug""",
          {"slug": slug,
           "status": ("healthy" if supported else "unsupported") if detail == "ok" else "unhealthy",
           "detail": f"balance: {balance}" if balance is not None else detail})


def resolve_fulfillment_provider(plan_source: str) -> ProviderAdapter:
    """The adapter that must fulfill a purchase of a catalog plan.

    With multi-provider routing disabled (the default and current
    production state), only WiseSub plans are purchasable and WiseSub
    fulfills them - exactly the pre-existing behavior.
    """
    source = (plan_source or "").strip().lower()
    if not settings.multi_provider_routing_enabled:
        active = primary_provider()
        if source != active:
            raise RuntimeError(f"Multi-provider routing is disabled; only {active} plans are purchasable")
        return _ADAPTERS[active]
    adapter = _ADAPTERS.get(source)
    if adapter is None or adapter.selection_excluded:
        raise RuntimeError(f"Provider '{source}' is excluded from fulfillment selection")
    if not adapter.is_configured() or not provider_enabled(source):
        raise RuntimeError(f"Provider '{source}' is not configured and enabled for fulfillment")
    return adapter


def safe_fallback_candidate(*, current_provider: str, outcome: str,
                            plan_source: str) -> str | None:
    """Decide whether a purchase may fall back to another provider.

    Safety gates (all must hold):
    - multi-provider routing is enabled;
    - the previous provider's outcome is FULLY known as failed AND that
      provider documents automatic refunds (uncertain or pending outcomes
      never trigger a fallback - they must be reconciled first);
    - a different, configured+enabled provider exists.

    Returns the fallback provider slug, or None when falling back is not
    safe. Package equivalence is verified separately by the caller via
    app/package_matching.py; a fallback is only ever attempted for an
    equivalent package.
    """
    if not settings.multi_provider_routing_enabled:
        return None
    current = _ADAPTERS.get(current_provider)
    if current is None:
        return None
    # UNCERTAIN / PENDING outcomes must never trigger a second purchase;
    # they are reconciled to a final state first.
    if outcome != "failed_final":
        return None
    if not current.auto_refunds_on_failure:
        return None
    for slug in eligible_provider_slugs():
        if slug != current_provider and slug != plan_source:
            return slug
    return None


def routing_status() -> dict:
    return {
        "multi_provider_routing_enabled": settings.multi_provider_routing_enabled,
        "primary_provider": primary_provider(),
        "eligible_providers": sorted(eligible_provider_slugs()),
        "excluded_providers": sorted(a.slug for a in all_adapters()
                                     if a.selection_excluded),
    }
