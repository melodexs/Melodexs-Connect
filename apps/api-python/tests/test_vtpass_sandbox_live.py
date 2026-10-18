"""Opt-in LIVE VTpass sandbox validation tests (real HTTP, sandbox only).

These run ONLY when ALL of the following hold:
- VTPASS_SANDBOX_LIVE_TESTS=1 is set explicitly (never by default),
- the three sandbox credential variables are configured,
- the configured base URL passes the fail-closed sandbox guard.

They exercise the documented sandbox scenarios against the verified
sandbox environment:
- GET authentication (balance) and catalog variations,
- POST authentication via the documented test phones:
  08011111111 (successful), 201000000000 (pending),
  400000000000 (no response), any other number (failed),
- duplicate request_id rejection (code 014),
- requery of every submitted request_id,
- wallet reversal behavior around failed purchases.

These are SANDBOX purchases on VTpass's documented mock environment:
no real carrier delivery, no real money, and the live host is refused
outright by the client. If credentials are missing, every test skips
(with a clear reason) rather than reaching for any live credential.
"""
import os
import uuid

import pytest

pytestmark_asyncio = pytest.mark.asyncio

from app import vtpass_sandbox
from app.config import settings
from app.provider_base import PurchaseOutcome
from app.vtpass_sandbox import VtpassSandboxClient, VtpassSandboxError, new_request_id


def _credentials_present() -> bool:
    return bool(settings.vtpass_sandbox_api_key
                and settings.vtpass_sandbox_public_key
                and settings.vtpass_sandbox_secret_key)


pytestmark = pytest.mark.skipif(
    not settings.vtpass_sandbox_live_tests or not _credentials_present(),
    reason="VTPASS sandbox live tests are opt-in: set VTPASS_SANDBOX_LIVE_TESTS=1 and the "
           "VTPASS_SANDBOX_API_KEY / VTPASS_SANDBOX_PUBLIC_KEY / VTPASS_SANDBOX_SECRET_KEY "
           "variables to run them")


@pytest.fixture
def client():
    instance = VtpassSandboxClient(
        api_key=settings.vtpass_sandbox_api_key or "",
        public_key=settings.vtpass_sandbox_public_key or "",
        secret_key=settings.vtpass_sandbox_secret_key or "",
        base_url=settings.vtpass_sandbox_base_url,
        timeout=60.0)
    # The fail-closed guard runs on every call: a live host configured by
    # mistake aborts the whole suite instead of sending a live purchase.
    assert instance.sandbox_base.endswith("sandbox.vtpass.com/api")
    return instance


def _ref() -> str:
    return new_request_id() + uuid.uuid4().hex[:6]


@pytest.mark.asyncio
async def test_sandbox_balance_and_get_authentication(client):
    balance = await client.balance()
    # Mock credit on the sandbox wallet; never real money.
    assert balance > 0


@pytest.mark.asyncio
async def test_sandbox_catalog_for_all_data_networks(client):
    # Verified serviceIDs: 9mobile data is "etisalat-data" on VTpass
    # ("9mobile-data" returns code 011 Service is Not Valid).
    for service_id, expected_fragment in [("mtn-data", "MTN"), ("glo-data", "Glo"),
                                          ("airtel-data", "Airtel"), ("etisalat-data", "9mobile")]:
        catalog = await client.service_variations(service_id)
        # Ambiguous (duplicated) codes are excluded from the variations
        # and reported explicitly; the live catalogs DO contain some
        # (verified 2026-10-18), so the invariant is detection, not absence.
        codes = [v.code for v in catalog.variations]
        assert len(codes) == len(set(codes)), f"{service_id} returned duplicate variation codes"
        assert not (set(catalog.duplicate_codes) & set(codes))
        assert catalog.variations, f"{service_id} returned no unambiguous variations"
        assert expected_fragment.lower() in catalog.service_name.lower()
        assert all(v.amount > 0 for v in catalog.variations)


@pytest.mark.asyncio
async def test_sandbox_purchase_success_scenario(client):
    ref = _ref()
    result = await client.purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                                   phone=vtpass_sandbox.TEST_PHONES and "08011111111",
                                   request_id=ref)
    assert result.outcome is PurchaseOutcome.SUCCESSFUL
    status = await client.requery(ref)
    assert status.recognized and status.status == "successful"


@pytest.mark.asyncio
async def test_sandbox_purchase_failed_scenario(client):
    ref = _ref()
    # Any non-test number simulates failure per the documentation.
    result = await client.purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                                   phone="08099990001", request_id=ref)
    assert result.outcome is PurchaseOutcome.UNCERTAIN  # VTpass documents no auto-refund
    status = await client.requery(ref)
    assert status.recognized and status.status == "failed"


@pytest.mark.asyncio
async def test_sandbox_purchase_pending_scenario(client):
    ref = _ref()
    result = await client.purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                                   phone="201000000000", request_id=ref)
    assert result.outcome is PurchaseOutcome.PENDING
    status = await client.requery(ref)
    assert status.recognized and status.status in {"pending", "successful"}


@pytest.mark.asyncio
async def test_sandbox_duplicate_request_id_is_rejected_not_replayed(client):
    ref = _ref()
    first = await client.purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                                  phone="08011111111", request_id=ref)
    assert first.outcome is PurchaseOutcome.SUCCESSFUL
    duplicate = await client.purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                                      phone="08011111111", request_id=ref)
    # Documented live behavior (code 014): the original response is NOT
    # replayed; the retry is uncertain and must be resolved by requery.
    assert duplicate.outcome is PurchaseOutcome.UNCERTAIN
    status = await client.requery(ref)
    assert status.recognized and status.status == "successful"


@pytest.mark.asyncio
async def test_sandbox_no_response_scenario_is_uncertain(client):
    ref = _ref()
    result = await client.purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                                   phone="400000000000", request_id=ref)
    # Documented "no response" phone: HTTP 200 with an empty body.
    assert result.outcome is PurchaseOutcome.UNCERTAIN
    status = await client.requery(ref)
    # The request may or may not have been accepted: either outcome is
    # legitimate; what matters is that the client did NOT guess.
    assert status.recognized is False or status.status in {"pending", "successful", "failed"}


@pytest.mark.asyncio
async def test_sandbox_reversal_behavior_around_failed_purchase(client):
    before = await client.balance()
    ref = _ref()
    await client.purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                          phone="08099990002", request_id=ref)
    after = await client.balance()
    # Verified live 2026-10-18: failed sandbox scenarios do not debit the
    # wallet (auto-reversed). If VTpass ever changes this, the test flags
    # it so the platform's refund logic can be re-reviewed.
    assert after >= before, "sandbox wallet was debited by a FAILED purchase"


@pytest.mark.asyncio
async def test_bad_credentials_produce_sanitized_errors(client):
    bad = VtpassSandboxClient(api_key="invalid", public_key="invalid",
                              secret_key="invalid",
                              base_url=settings.vtpass_sandbox_base_url)
    with pytest.raises(VtpassSandboxError):
        await bad.balance()
