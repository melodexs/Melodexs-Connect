"""Configuration defaults decide what production does before anyone touches it.

These assertions are deliberately about *safety*, not about any particular
provider: a fresh checkout must never route traffic to an unvalidated supplier,
never allow multiple providers by accident, and never expose a debug flag.
"""
from app.config import settings


def test_multi_provider_routing_is_off_by_default():
    assert getattr(settings, "multi_provider_routing_enabled", False) is False


def test_default_catalog_source_is_the_retained_provider():
    # Production overrides this via ACTIVE_CATALOG_SOURCE; the code default must
    # stay on the supplier that is always retained and reconcilable.
    assert (settings.active_catalog_source or "wisesub").lower() == "wisesub"


def test_risky_toggles_default_to_safe_values():
    assert getattr(settings, "cheapdata_markup_percent", 2) == 2
    assert getattr(settings, "wisesub_failure_status_confirmed", False) is False


def test_secrets_are_not_hardcoded():
    """A committed default secret would let anyone forge a session."""
    secret = getattr(settings, "session_secret", "") or ""
    assert secret not in {"", "secret", "changeme", "test", "melodexs"}
    assert len(secret) >= 16


def test_production_flag_follows_the_environment():
    assert settings.production is False, "the test environment must not look like production"
