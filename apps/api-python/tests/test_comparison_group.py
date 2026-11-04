"""ComparisonGroup: picking the cheapest supplier and reporting quotes safely."""
from decimal import Decimal

from app.price_comparison import ComparisonGroup, SupplierQuote


def quote(provider, cost, available=True, plan_id=1, override=None):
    return SupplierQuote(provider=provider, plan_id=plan_id, package_code=f"{provider}-1gb",
                         plan_name="1GB monthly", supplier_cost=Decimal(str(cost)),
                         selling_price=Decimal(str(cost)) + Decimal("5"),
                         price_override=Decimal(str(override)) if override is not None else None,
                         available=available)


def group(*quotes):
    return ComparisonGroup(network="MTN", data_size="1GB", size_mb=Decimal(1024), validity_days=30,
                           family=None, eligible=False, reason="family unknown", quotes=list(quotes))


def test_the_cheapest_available_supplier_wins():
    g = group(quote("wisesub", 300), quote("isquaredata", 280, plan_id=2))
    assert g.cheapest_available.provider == "isquaredata"


def test_an_unavailable_supplier_is_never_chosen_even_if_cheaper():
    g = group(quote("wisesub", 300), quote("isquaredata", 100, available=False, plan_id=2))
    assert g.cheapest_available.provider == "wisesub"


def test_nothing_is_chosen_when_no_supplier_is_available():
    g = group(quote("wisesub", 300, available=False), quote("isquaredata", 280, available=False, plan_id=2))
    assert g.cheapest_available is None
    assert g.to_dict()["cheapest_provider"] is None


def test_an_empty_group_has_no_cheapest():
    assert group().cheapest_available is None


def test_the_report_converts_money_to_numbers_and_flags_pinned_prices():
    out = group(quote("wisesub", 300, override=450)).to_dict()
    row = out["quotes"][0]
    assert (row["supplier_cost"], row["selling_price"], row["customer_price_override"]) == (300.0, 305.0, 450.0)
    assert out["size_mb"] == 1024.0 and out["eligible"] is False and out["reason"] == "family unknown"


def test_a_quote_without_a_pinned_price_reports_none():
    assert group(quote("wisesub", 300)).to_dict()["quotes"][0]["customer_price_override"] is None


def test_the_report_lists_available_quotes_first_then_by_cost_descending():
    g = group(quote("a", 100, available=False, plan_id=1), quote("b", 200, plan_id=2), quote("c", 150, plan_id=3))
    order = [(r["provider"], r["available"]) for r in g.to_dict()["quotes"]]
    assert order == [("b", True), ("c", True), ("a", False)]


def test_decimal_costs_do_not_pick_up_float_error():
    g = group(quote("a", "0.1"), quote("b", "0.3", plan_id=2))
    assert g.cheapest_available.supplier_cost + Decimal("0.2") == Decimal("0.3")
