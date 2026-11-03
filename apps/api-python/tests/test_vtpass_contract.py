"""VTpass sandbox contract tests (MOCKED - no network access required).

These verify the validation client's request construction, response
mapping, and safety gates against the contract verified on 2026-10-18:
- fail-closed sandbox URL guard (live hosts are never usable),
- GET (api-key + public-key) vs POST (api-key + secret-key) headers,
- balance parsing, catalog normalization and duplicate/malformed detection,
- purchase outcome mapping (delivered / pending / failed / duplicate /
  empty-body / timeout), requery mapping, request_id rules,
- credentials never appear in exceptions or messages.
"""
import json

import httpx
import pytest

from app.provider_base import PurchaseOutcome
from app import vtpass_sandbox
from app.vtpass_sandbox import (VtpassSandboxClient, VtpassSandboxError,
                                 assert_sandbox_url, new_request_id,
                                 request_id_is_wellformed)

CREDS = dict(api_key="k" * 32, public_key="pk" * 10, secret_key="sk" * 10)


def client(**overrides):
    return VtpassSandboxClient(**{**CREDS, **overrides})


class _Response:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self._text = text

    def json(self):
        if self._text is not None:
            raise ValueError("no json")
        return self._body


class _FakeClient:
    """Records calls; returns canned responses per endpoint."""

    def __init__(self, responses=None, error=None, **kwargs):
        self.options = kwargs
        self._responses = responses or {}
        self._error = error
        self.calls = []
        _FakeClient.instances.append(self)

    instances: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def _handle(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self._error is not None:
            raise self._error
        for key, response in self._responses.items():
            if key in url:
                return response
        return _Response()

    async def get(self, url, **kwargs):
        return await self._handle("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return await self._handle("POST", url, **kwargs)


@pytest.fixture(autouse=True)
def reset():
    _FakeClient.instances = []
    yield
    _FakeClient.instances = []


def patch_async(monkeypatch, responses=None, error=None):
    def factory(**kwargs):
        return _FakeClient(responses=responses, error=error, **kwargs)
    monkeypatch.setattr(vtpass_sandbox.httpx, "AsyncClient", factory)


# ------------------------------------------------------------- URL guard

def test_sandbox_url_guard_accepts_only_the_documented_sandbox_host():
    assert assert_sandbox_url("https://sandbox.vtpass.com/api") == "https://sandbox.vtpass.com/api"
    assert assert_sandbox_url("https://SANDBOX.VTPass.com/api/whatever") == "https://sandbox.vtpass.com/api"


@pytest.mark.parametrize("bad", [
    "https://vtpass.com/api",              # live host
    "https://api.vtpass.com",              # unknown host
    "http://sandbox.vtpass.com/api",       # not https
    "https://sandbox.vtpass.com.evil.io/api",  # suffix attack
    "https://sandbox.vtpass.com@evil.io/api",  # userinfo attack (credentials style)
    "https://user@sandbox.vtpass.com/api",     # userinfo prefix
    "https://sandbox.vtpass.com:8443/api",     # non-default port
    "ftp://sandbox.vtpass.com/api",
    "", None,
])
def test_sandbox_url_guard_fails_closed_on_non_sandbox_urls(bad):
    with pytest.raises(VtpassSandboxError):
        assert_sandbox_url(bad)
    # The client refuses network calls built on a non-sandbox base URL.
    bad_client = client(base_url=bad or "")
    with pytest.raises(VtpassSandboxError):
        bad_client.sandbox_base


def test_client_requires_all_three_credentials(monkeypatch):
    for missing in ("api_key", "public_key", "secret_key"):
        with pytest.raises(VtpassSandboxError):
            client(**{missing: ""})._get_headers()
        with pytest.raises(VtpassSandboxError):
            client(**{missing: ""})._post_headers()


# ----------------------------------------------------------- request ids

def test_request_id_generation_and_rules():
    rid = new_request_id()
    assert request_id_is_wellformed(rid)
    assert len(rid) == 22 and rid[:12].isdigit() and rid.isalnum()
    for bad in ["", "short", "a" * 12, "20261018" + "!" * 10, 123, None]:
        assert not request_id_is_wellformed(bad)


# -------------------------------------------------------------- balance

@pytest.mark.asyncio
async def test_balance_uses_get_headers_and_parses_amount(monkeypatch):
    ok = _Response(body={"code": 1, "contents": {"balance": "2000000.00"}})
    patch_async(monkeypatch, responses={"/balance": ok})
    value = await client().balance()
    assert str(value) == "2000000.00"
    call = _FakeClient.instances[0].calls[0]
    assert call[0] == "GET" and call[1].endswith("/balance")
    headers = call[2]["headers"]
    assert headers["api-key"] == CREDS["api_key"]
    assert headers["public-key"] == CREDS["public_key"]
    assert "secret-key" not in headers  # GET never carries the secret key


@pytest.mark.asyncio
async def test_balance_rejects_credential_errors_without_leaking_secrets(monkeypatch):
    bad = _Response(status_code=401, body={"message": "Invalid Credentials."})
    patch_async(monkeypatch, responses={"/balance": bad})
    with pytest.raises(VtpassSandboxError) as exc:
        await client().balance()
    assert CREDS["api_key"] not in str(exc.value)
    assert CREDS["secret_key"] not in str(exc.value)


# --------------------------------------------------------------- catalog

GOOD_VARIATIONS = {"response_description": "000", "content": {"variations": [
    {"variation_code": "mtn-10mb-100", "name": "N100 100MB - 24 hrs",
     "variation_amount": "100.00", "fixedPrice": "Yes"},
    {"variation_code": "mtn-3gb-2500", "name": "N2500 6GB - 30 days",
     "variation_amount": "2500.00", "fixedPrice": "Yes"},
]}}


@pytest.mark.asyncio
async def test_service_variations_normalize_structure(monkeypatch):
    patch_async(monkeypatch, responses={"service-variations": _Response(body=GOOD_VARIATIONS)})
    catalog = await client().service_variations("mtn-data")
    assert catalog.duplicate_codes == []
    assert [v.code for v in catalog.variations] == ["mtn-10mb-100", "mtn-3gb-2500"]
    first = catalog.variations[0]
    assert str(first.amount) == "100.00"
    assert first.data_size == "100MB"
    assert first.validity == "24 hrs"
    assert catalog.variations[1].data_size == "6GB"
    assert catalog.variations[1].fixed_price is True
    # Last-hyphen validity parsing (live airtel-data name shape).
    size, validity = vtpass_sandbox._parse_variation_name(
        "Airtel Data Bundle - 50 Naira - 25MB  - 1Day")
    assert size == "25MB" and validity == "1Day"
    call = _FakeClient.instances[0].calls[0]
    assert call[2]["params"] == {"serviceID": "mtn-data"}


GOOD_DUP_VARIATIONS = {"response_description": "000", "content": {"variations": [
    {"variation_code": "mtn-xtratalk-300", "name": "N300 XtraTalk", "variation_amount": "300"},
    {"variation_code": "mtn-xtratalk-300", "name": "N300 XtraTalk", "variation_amount": "300"},
]}}


@pytest.mark.asyncio
async def test_duplicate_variation_codes_are_reported_never_deduped(monkeypatch):
    # Verified live: VTpass catalogs can repeat a variation_code. The
    # validation reports the ambiguity and never treats the ambiguous
    # code as a distinct purchasable product.
    patch_async(monkeypatch, responses={"service-variations": _Response(body=GOOD_DUP_VARIATIONS)})
    catalog = await client().service_variations("mtn-data")
    assert catalog.duplicate_codes == ["mtn-xtratalk-300"]
    assert catalog.variations == []
    assert catalog.service_id == "mtn-data"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate", [
    lambda b: b.update({"response_description": "011"}),
    lambda b: b["content"].update({"variations": []}),
    lambda b: b["content"].update({"variations": [{"name": "no code", "variation_amount": "10"}]}),
    lambda b: b["content"].update({"variations": [
        {"variation_code": "bad-amount", "variation_amount": "free"}]}),
    lambda b: b["content"].update({"variations": [
        {"variation_code": "nameless", "variation_amount": "5"}]}),
])
async def test_catalog_failures_are_never_silently_purchasable(monkeypatch, mutate):
    import copy
    body = copy.deepcopy(GOOD_VARIATIONS)
    mutate(body)
    patch_async(monkeypatch, responses={"service-variations": _Response(body=body)})
    with pytest.raises(VtpassSandboxError):
        await client().service_variations("mtn-data")


# -------------------------------------------------------------- purchase

@pytest.mark.asyncio
async def test_purchase_success_maps_delivered(monkeypatch):
    body = {"code": "000", "response_description": "TRANSACTION SUCCESSFUL",
            "content": {"transactions": {"status": "delivered"}}}
    patch_async(monkeypatch, responses={"/pay": _Response(body=body)})
    result = await client().purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                                     phone="08011111111", request_id=new_request_id())
    assert result.outcome is PurchaseOutcome.SUCCESSFUL
    call = _FakeClient.instances[0].calls[0]
    assert call[0] == "POST" and call[1].endswith("/pay")
    headers = call[2]["headers"]
    assert headers["api-key"] == CREDS["api_key"]
    assert headers["secret-key"] == CREDS["secret_key"]
    assert "public-key" not in headers  # POST never carries the public key
    payload = call[2]["json"]
    # Documented recipient field is "phone", not billersCode.
    assert payload["phone"] == "08011111111"
    assert payload["serviceID"] == "mtn-data"
    assert payload["variation_code"] == "mtn-10mb-100"
    assert request_id_is_wellformed(payload["request_id"])


@pytest.mark.asyncio
async def test_purchase_pending_and_failed_and_duplicate_mapping(monkeypatch):
    pending = {"code": "000", "response_description": "TRANSACTION PROCESSING",
               "content": {"transactions": {"status": "pending"}}}
    failed = {"code": "016", "response_description": "TRANSACTION FAILED",
              "content": {"transactions": {"status": "failed"}}}
    duplicate = {"code": "014", "response_description": "REQUEST ID ALREADY EXIST"}
    patch_async(monkeypatch, responses={"/pay": _Response(body=pending)})
    result = await client().purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                                     phone="201000000000", request_id=new_request_id())
    assert result.outcome is PurchaseOutcome.PENDING
    patch_async(monkeypatch, responses={"/pay": _Response(body=failed)})
    result = await client().purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                                     phone="08031234577", request_id=new_request_id())
    # VTpass does not document an automatic wallet refund: failed stays
    # UNCERTAIN for reconciliation, never an auto-refund.
    assert result.outcome is PurchaseOutcome.UNCERTAIN
    patch_async(monkeypatch, responses={"/pay": _Response(body=duplicate)})
    result = await client().purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                                     phone="08011111111", request_id=new_request_id())
    assert result.outcome is PurchaseOutcome.UNCERTAIN


@pytest.mark.asyncio
async def test_purchase_timeout_and_empty_body_are_uncertain(monkeypatch):
    # Documented timeout scenario (300000000000): transport error.
    patch_async(monkeypatch, error=httpx.ReadTimeout("timed out"))
    result = await client().purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                                     phone="300000000000", request_id=new_request_id())
    assert result.outcome is PurchaseOutcome.UNCERTAIN
    # Documented no-response scenario (400000000000): HTTP 200, empty body.
    patch_async(monkeypatch, responses={"/pay": _Response(text="")})
    result = await client().purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                                     phone="400000000000", request_id=new_request_id())
    assert result.outcome is PurchaseOutcome.UNCERTAIN


@pytest.mark.asyncio
async def test_purchase_rejects_malformed_request_id(monkeypatch):
    patch_async(monkeypatch)
    with pytest.raises(VtpassSandboxError):
        await client().purchase(service_id="mtn-data", variation_code="mtn-10mb-100",
                                phone="08011111111", request_id="bad-id")


# --------------------------------------------------------------- requery

@pytest.mark.asyncio
async def test_requery_maps_documented_statuses(monkeypatch):
    delivered = {"response_description": "TRANSACTION SUCCESSFUL", "code": "000",
                 "content": {"transactions": {"status": "delivered"}}}
    failed = {"response_description": "TRANSACTION FAILED", "code": "016",
              "content": {"transactions": {"status": "failed"}}}
    pending = {"response_description": "TRANSACTION PROCESSING - PENDING", "code": "000",
               "content": {"transactions": {"status": "pending"}}}
    unknown = {"code": "015", "response_description": "INVALID REQUEST ID",
               "content": {"errors": ""}}
    for body, expected in [(delivered, ("successful", True)), (failed, ("failed", True)),
                           (pending, ("pending", True)), (unknown, (None, False))]:
        patch_async(monkeypatch, responses={"/requery": _Response(body=body)})
        status = await client().requery(new_request_id())
        assert (status.status, status.recognized) == expected
    call = _FakeClient.instances[0].calls[0]
    assert call[0] == "POST" and call[1].endswith("/requery")
    assert "request_id" in call[2]["json"]
    assert call[2]["headers"]["secret-key"] == CREDS["secret_key"]


@pytest.mark.asyncio
async def test_requery_reversed_transaction_maps_failed(monkeypatch):
    # Webhook docs: inner status "reversed" with code 040 = TRANSACTION
    # REVERSED TO WALLET (provider refunded the wallet).
    reversed_body = {"code": "040", "response_description": "TRANSACTION REVERSED TO WALLET",
                     "content": {"transactions": {"status": "reversed"}}}
    patch_async(monkeypatch, responses={"/requery": _Response(body=reversed_body)})
    status = await client().requery(new_request_id())
    assert status.recognized and status.status == "failed"


@pytest.mark.asyncio
async def test_documented_test_phone_table_is_preserved():
    # Guard against silently inventing or losing sandbox scenarios.
    assert vtpass_sandbox.TEST_PHONES["08011111111"] == "successful"
    assert vtpass_sandbox.TEST_PHONES["201000000000"] == "pending"
    assert vtpass_sandbox.TEST_PHONES["300000000000"] == "timeout"
    assert vtpass_sandbox.TEST_PHONES["400000000000"] == "no_response"
    assert vtpass_sandbox.TEST_PHONES["500000000000"] == "unexpected"


# ------------------------------------------------------------ secret hygiene

@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["balance", "service-variations", "pay", "requery"])
async def test_redirect_responses_are_never_followed(endpoint, monkeypatch):
    """A sandbox request must never follow a redirect to any host (live
    included). Regression guard: every client is built with
    follow_redirects=False and a single call is made - the 3xx itself is
    an error/uncertain outcome, never a hop."""
    redirect = _Response(status_code=308, text="Redirecting...")
    patch_async(monkeypatch, responses={endpoint: redirect})
    c = client()
    if endpoint == "balance":
        with pytest.raises(VtpassSandboxError):
            await c.balance()
    elif endpoint == "service-variations":
        with pytest.raises(VtpassSandboxError):
            await c.service_variations("mtn-data")
    elif endpoint == "pay":
        result = await c.purchase(service_id="mtn-data", variation_code="v",
                                  phone="08011111111", request_id=new_request_id())
        assert result.outcome is PurchaseOutcome.UNCERTAIN
    else:
        result = await c.requery(new_request_id())
        assert result.recognized is False
    fake = _FakeClient.instances[0]
    assert fake.options.get("follow_redirects") is False
    assert len(fake.calls) == 1, "a redirect response must not trigger a second request"


@pytest.mark.asyncio
async def test_no_credentials_in_results_or_errors(monkeypatch):
    weird = _Response(body={"code": "029", "response_description": CREDS["secret_key"]})
    patch_async(monkeypatch, responses={"/pay": _Response(text="")})
    result = await client().purchase(service_id="mtn-data", variation_code="x",
                                     phone="400000000000", request_id=new_request_id())
    assert result.raw is None  # empty body: nothing recorded
    patch_async(monkeypatch, responses={"/pay": _Response(status_code=500, body={"code": "500"})})
    result = await client().purchase(service_id="mtn-data", variation_code="x",
                                     phone="500000000000", request_id=new_request_id())
    dumped = json.dumps(result.raw or {})
    assert CREDS["api_key"] not in (result.message + dumped)
