"""Capabilities decide which adapter may be tried for a purchase.

An adapter that claims a capability it cannot honour will be selected and then
fail, after the customer has been debited. An adapter that claims too little is
unreachable. Both are worth pinning.
"""
from app.provider_base import ProviderAdapter
from app.provider_registry import _ADAPTERS, default_adapters

VALID = {"catalog", "data", "airtime", "status", "balance"}


def test_every_adapter_declares_known_capabilities():
    for adapter in default_adapters():
        assert adapter.capabilities, f"{adapter.slug} declares no capabilities"
        unknown = set(adapter.capabilities) - VALID
        assert not unknown, f"{adapter.slug} declares unknown capabilities: {unknown}"


def test_every_adapter_implements_the_interface():
    for adapter in default_adapters():
        assert isinstance(adapter, ProviderAdapter)
        assert adapter.slug and adapter.display_name
        assert isinstance(adapter.is_configured(), bool)


def test_slugs_are_unique_and_registered():
    slugs = [a.slug for a in default_adapters()]
    assert len(slugs) == len(set(slugs)), "two adapters share a slug"
    assert set(slugs) == set(_ADAPTERS), "the registry and the adapter list disagree"


def test_the_retained_provider_is_always_registered():
    """WiseSub must never disappear: it is the fallback and the airtime route."""
    assert "wisesub" in _ADAPTERS


def test_retired_adapters_cannot_be_selected():
    for slug, adapter in _ADAPTERS.items():
        if getattr(adapter, "selection_excluded", False):
            assert slug != "isquaredata", "the primary provider must stay selectable"


def test_a_data_provider_also_declares_a_catalog():
    """You cannot route to a plan you cannot list."""
    for adapter in default_adapters():
        if "data" in adapter.capabilities:
            assert "catalog" in adapter.capabilities, (
                f"{adapter.slug} sells data but cannot list a catalogue")
