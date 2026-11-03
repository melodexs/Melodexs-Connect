"""Phone numbers are how bundles reach customers, so validation matters.

Airtime and data are delivered to the number exactly as submitted; accepting a
malformed one means the supplier rejects the order after the wallet moved.
"""
import pytest

from app.main import nigeria_phone


@pytest.mark.parametrize("value", [
    "08030000000", "08051234567", "08105922884", "09012345678", "07012345678",
    "2348030000000", "+2348030000000", "2348051234567",
])
def test_accepts_nigerian_mobile_formats(value):
    assert nigeria_phone(value) is True


@pytest.mark.parametrize("value", [
    "", "0803000000", "080300000000", "12345", "0803abc0000",
    "18030000000", "+12348030000000", "0803000000 ", "   ",
])
def test_rejects_malformed_numbers(value):
    assert nigeria_phone(value) is False


def test_accepts_a_numeric_type_without_crashing():
    # Numbers arrive as strings from JSON, but an integer must not raise.
    assert nigeria_phone(8030000000) is True
