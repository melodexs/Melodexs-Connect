"""Family labels and match keys: uncertain packages must never auto-match."""
import pytest

from app.package_matching import normalize_family, package_key


@pytest.mark.parametrize("label,family", [
    ("Corporate Gifting", "corporate"), ("CG", "corporate"), ("sme", "sme"),
    ("Gift", "gifting"), ("GIFTING", "gifting"), ("Normal", "standard"),
    ("  standard  ", "standard"), ("Special Offer", "special offer"),
])
def test_family_labels_are_normalised(label, family):
    assert normalize_family(label) == family


@pytest.mark.parametrize("label", [None, "", "   "])
def test_a_missing_family_stays_unknown(label):
    assert normalize_family(label) is None


def _key(**over):
    base = dict(network="MTN", data_size="1GB", validity="30 days", plan_type="sme")
    base.update(over)
    return package_key(**base)


def test_the_same_package_from_two_providers_matches():
    assert _key().matches(_key(data_size="1024MB", validity="1 month", network="mtn"))


@pytest.mark.parametrize("field,value", [
    ("network", "Airtel"), ("data_size", "2GB"), ("validity", "7 days"), ("plan_type", "gifting"),
])
def test_changing_any_one_attribute_breaks_the_match(field, value):
    assert not _key().matches(_key(**{field: value}))


@pytest.mark.parametrize("over", [
    {"data_size": None}, {"validity": None}, {"plan_type": None},
    {"data_size": "unlimited"}, {"network": "Vodafone"}, {"network": None},
])
def test_an_unknown_attribute_makes_the_package_ineligible(over):
    assert _key(**over) is None


def test_an_unknown_family_never_matches_even_itself():
    from app.package_matching import PackageKey
    from decimal import Decimal
    unknown = PackageKey("MTN", Decimal(1024), 30, None)
    assert not unknown.matches(unknown)
    assert not unknown.matches(_key())
    assert not _key().matches(unknown)


def test_network_names_are_case_insensitive_and_canonicalised():
    assert _key(network=" GLO ").network == "Glo"
    assert _key(network="9MOBILE").network == "9mobile"
