"""Size and validity parsing used by provider package matching."""
from decimal import Decimal

import pytest

from app.package_matching import size_to_mb, validity_to_days


@pytest.mark.parametrize("text,mb", [
    ("500MB", "500"), ("500 mb", "500"), ("1GB", "1024"), ("1.5GB", "1536"),
    ("2 GB", "2048"), ("10GB", "10240"), ("1TB", "1048576"),
    ("1024KB", "1.024"), ("MTN 3.5GB Monthly", "3584"),
])
def test_sizes_convert_to_megabytes_using_1024(text, mb):
    assert size_to_mb(text) == Decimal(mb)


@pytest.mark.parametrize("text", [None, "", "unlimited", "GB", "abc MB", "0MB", "0GB"])
def test_unreadable_or_zero_sizes_are_unknown_never_guessed(text):
    assert size_to_mb(text) is None


@pytest.mark.parametrize("text,days", [
    ("1 day", 1), ("2 days", 2), ("30 Days", 30), ("1 week", 7), ("2 weeks", 14),
    ("1 month", 30), ("3 months", 90), ("12 hours", 1), ("24hrs", 1),
    ("daily", 1), ("Weekly", 7), ("monthly", 30),
])
def test_validity_phrases_convert_to_days(text, days):
    assert validity_to_days(text) == days


@pytest.mark.parametrize("text", [None, "", "   ", "forever", "no expiry"])
def test_unknown_validity_is_none(text):
    assert validity_to_days(text) is None


def test_sub_day_validity_is_kept_distinct_from_nothing():
    # Hours are rounded to one day so they can still be compared, never dropped.
    assert validity_to_days("6 hours") == 1
