"""Opt-in LIVE MELE DATA verification tests (test token only, never live keys).

These run ONLY when ALL of the following hold:
- MELEDATA_LIVE_TESTS=1 is set explicitly (never by default),
- MELEDATA_API_KEY is configured,
- MELEDATA_TEST_MODE=1 is set (the module refuses to run otherwise).

MELE DATA has ONE base URL for live and test traffic; the token selects
the mode. These tests therefore prove the fail-closed mode gate against
the real service: every wallet response must report mode="test" and
livemode=false, or the adapter (and this suite) refuses to continue.

Verified live 2026-10-18 (test token):
- /wallet reports {"balance": 1000000.0, "currency": "NGN",
  "livemode": false, "mode": "test"},
- /data/plans returns {"status": true, "data": {"plans": [...]}} with
  integer plan_id values,
- test purchases currently return HTTP 400 "Insufficient wallet
  balance." against the test balance (provider limitation: MELE test
  purchases are NOT verified end-to-end; purchase logic is covered by
  mocked contract tests),
- unowned requery references return a "not owned" error (unrecognized).

No live credential is ever used, no wallet is funded, and nothing here
can reach a real customer.

READ-ONLY BY DEFAULT: with only MELEDATA_LIVE_TESTS=1 the suite issues
wallet, catalog and requery requests only - none of which can initiate
a transaction. The single purchase-attempt test additionally requires
MELEDATA_PURCHASE_TESTS=1 (a second, independent opt-in) so no live
verification run ever calls a purchase endpoint by accident.
"""
import pytest

from app.config import settings
from app.provider_base import PurchaseOutcome
from app.provider_meledata import MeleDataAdapter

pytestmark = pytest.mark.skipif(
    not getattr(settings, "meledata_live_tests", False)
    or not settings.meledata_api_key
    or not settings.meledata_test_mode,
    reason="MELE DATA live tests are opt-in: set MELEDATA_LIVE_TESTS=1, MELEDATA_TEST_MODE=1 "
           "and MELEDATA_API_KEY (a mele_test_... token) to run them")


@pytest.fixture
def adapter():
    return MeleDataAdapter()


@pytest.mark.asyncio
async def test_test_token_wallet_reports_test_mode(adapter):
    result = await adapter.account_balance()
    assert result.supported, result.message
    assert result.mode == "test", f"expected test mode, got {result.mode!r}"
    assert result.livemode is False
    assert result.currency == "NGN"
    assert result.balance > 0


@pytest.mark.asyncio
async def test_live_catalog_uses_integer_plan_ids(adapter):
    packages = await adapter.fetch_catalog()
    assert packages, "catalog returned no plans"
    for package in packages:
        # The adapter exposes plan_id as the purchase key; it must be
        # parseable as an int (documented MELE type).
        int(package.code)
        assert package.network in {"MTN", "Airtel", "Glo", "9mobile"}
        assert package.cost > 0
    codes = [p.code for p in packages]
    # No duplicate plan purchase keys.
    assert len(codes) == len(set(codes))


@pytest.mark.asyncio
@pytest.mark.skipif(
    not getattr(settings, "meledata_purchase_tests", False),
    reason="Purchase attempts are a SEPARATE opt-in: set MELEDATA_PURCHASE_TESTS=1 "
           "(plus MELEDATA_LIVE_TESTS=1, MELEDATA_TEST_MODE=1) to run this one test")
async def test_test_purchase_is_safely_refused_without_a_wallet_debit(adapter):
    """Provider limitation (2026-10-18): test purchases return HTTP 400
    'Insufficient wallet balance.' even against the test wallet. The
    safety property: the adapter NEVER turns that into a confirmed
    failure or success, and the test wallet is never debited."""
    before = await adapter.account_balance()
    assert before.supported
    packages = await adapter.fetch_catalog()
    cheapest = min(packages, key=lambda p: p.cost)
    result = await adapter.submit_data_purchase(
        network=cheapest.network, package_code=cheapest.code,
        phone="08031234567",
        reference=f"SANDBOX_TEST_pytest_{cheapest.code}")
    assert result.outcome is not PurchaseOutcome.SUCCESSFUL
    assert result.outcome is not PurchaseOutcome.FAILED_FINAL
    after = await adapter.account_balance()
    assert after.supported
    assert after.balance == before.balance, "test wallet was debited by a refused purchase"


@pytest.mark.asyncio
async def test_unowned_reference_requery_is_unrecognized(adapter):
    outcome = await adapter.transaction_status("SANDBOX_TEST_pytest_never_purchased")
    # The provider's ownership error is not a purchase outcome: never
    # recognized as success or failure.
    assert outcome.recognized is False
