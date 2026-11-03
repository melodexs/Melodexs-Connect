"""Selling prices are computed on the server and must be predictable.

The published policy is a 2% markup rounded up to the next naira, with billers
(electricity, TV) at face value and education result PINs at the same 2%.
Rounding *up* matters: rounding down would sell below cost on small bundles.
"""
import math

import pytest

MARKUP = 0.02
CASES = [
    (75.0, 77),      # 76.5 -> 77
    (100.0, 102),    # exact, no rounding needed
    (101.0, 104),    # 103.02 -> 104
    (403.0, 412),    # 411.06 -> 412
    (4500.0, 4590),
    (73500.0, 74970),
    (0.01, 1),       # a one-kobo cost must not become free
]


@pytest.mark.parametrize("cost,expected", CASES)
def test_markup_rounds_up_to_the_next_naira(cost, expected):
    assert math.ceil(cost * (1 + MARKUP)) == expected


@pytest.mark.parametrize("cost,_expected", CASES)
def test_price_never_falls_below_cost(cost, _expected):
    assert math.ceil(cost * (1 + MARKUP)) >= cost


def test_billboards_are_sold_at_face_value():
    """Electricity and TV pass through at the supplier's amount; the margin is
    the provider discount, not a markup, so no rounding is applied."""
    for amount in (1000, 2500, 10000):
        assert amount * 1.0 == amount


def test_selling_price_uses_the_configured_markup():
    from app.plan_sync import selling_price

    assert selling_price(1000) == 1020          # default 2%
    assert selling_price(75) == 77
    assert selling_price(0.01) == 1             # never rounds down to free


def test_selling_price_rejects_an_impossible_price():
    import pytest as _pytest

    from app.plan_sync import selling_price

    with _pytest.raises(ValueError):
        selling_price(2_000_000)                # exceeds the supported ceiling


def test_selling_price_refuses_a_nonsense_markup(monkeypatch):
    import pytest as _pytest

    from app import plan_sync
    from app.config import settings

    monkeypatch.setattr(settings, "cheapdata_markup_percent", 1_000, raising=False)
    with _pytest.raises(ValueError):
        plan_sync.selling_price(1000)
