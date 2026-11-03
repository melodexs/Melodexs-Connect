"""Biller menus are cached briefly; money paths are never served from the cache.

The listing endpoints used to hit the supplier on every page open (0.5-1.1s).
Caching them is safe because they are read-only menus. Purchases and
verification must keep revalidating against the live supplier, so the cache
helper is only allowed in the three listing handlers.
"""
import asyncio
import re
from pathlib import Path

import pytest

from app import main

SRC = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text()


@pytest.fixture(autouse=True)
def _clear_cache():
    main._biller_list_cache.clear()
    yield
    main._biller_list_cache.clear()


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_a_second_call_is_served_from_the_cache():
    calls = []

    async def loader():
        calls.append(1)
        return [{"id": 1, "name": "IKEDC"}]

    first = run(main._cached_biller_list("electricity", loader))
    second = run(main._cached_biller_list("electricity", loader))
    assert first == second == [{"id": 1, "name": "IKEDC"}]
    assert len(calls) == 1, "the supplier should be called once inside the TTL"


def test_callers_cannot_mutate_the_cached_copy():
    """Education adds selling_price to each row; that must not leak back."""
    async def loader():
        return [{"id": 1, "api_amount": 100}]

    one = run(main._cached_biller_list("education", loader))
    one[0]["selling_price"] = 999
    two = run(main._cached_biller_list("education", loader))
    assert "selling_price" not in two[0]


def test_an_expired_entry_is_refreshed(monkeypatch):
    calls = []

    async def loader():
        calls.append(1)
        return [{"id": len(calls)}]

    run(main._cached_biller_list("cable", loader))
    stamp, items = main._biller_list_cache["cable"]
    main._biller_list_cache["cable"] = (stamp - main._BILLER_LIST_TTL - 1, items)
    refreshed = run(main._cached_biller_list("cable", loader))
    assert len(calls) == 2
    assert refreshed == [{"id": 2}]


def test_a_supplier_outage_serves_the_stale_copy():
    async def good():
        return [{"id": 1}]

    async def broken():
        raise RuntimeError("supplier down")

    run(main._cached_biller_list("cable", good))
    stamp, items = main._biller_list_cache["cable"]
    main._biller_list_cache["cable"] = (stamp - main._BILLER_LIST_TTL - 1, items)
    assert run(main._cached_biller_list("cable", broken)) == [{"id": 1}]


def test_an_outage_with_nothing_cached_still_errors():
    async def broken():
        raise RuntimeError("supplier down")

    with pytest.raises(RuntimeError):
        run(main._cached_biller_list("electricity", broken))


def test_the_cache_is_used_only_by_the_listing_handlers():
    """Verify and purchase handlers must keep calling the live supplier."""
    allowed = {"billers_electricity", "billers_cable", "billers_education"}
    used_in = set()
    # Only real calls (awaited), not the helper's own definition.
    for match in re.finditer(r"await _cached_biller_list\(", SRC):
        handler = re.findall(r"(?:async )?def (\w+)\(", SRC[:match.start()])[-1]
        used_in.add(handler)
    assert used_in == allowed, f"cache used in {used_in}, expected exactly {allowed}"


def test_purchase_and_verify_still_read_the_live_supplier():
    for handler in ("purchase_electricity", "purchase_cable", "purchase_education",
                    "billers_electricity_verify", "billers_cable_verify"):
        match = re.search(rf"def {handler}\(.*?(?=\n@app\.|\Z)", SRC, re.S)
        assert match, f"{handler} not found"
        assert "_cached_biller_list" not in match.group(0), (
            f"{handler} handles money or identity and must not use the cache")
