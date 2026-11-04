"""Wallet deposit fee: pay N1,000 at 3% and the wallet receives N970.

These run the real create -> Paystack-confirms -> credit path with Paystack
mocked, and assert on the actual wallet balance, because that is the money.
"""
import hashlib
import hmac
import json
import secrets
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import deposit_fee, main
from app.config import settings
from app.database import db_session, q


# ---------------------------------------------------------------- pure maths

@pytest.mark.parametrize("paid,fee,credit", [
    (500, 15, 485), (1000, 30, 970), (1500, 45, 1455), (2000, 60, 1940),
    (2500, 75, 2425), (3000, 90, 2910), (3500, 105, 3395), (4000, 120, 3880),
    (4500, 135, 4365), (5000, 150, 4850),
])
def test_three_percent_matches_the_agreed_table(paid, fee, credit):
    s = deposit_fee.split(paid, 3)
    assert (s["paid"], s["fee"], s["credit"]) == (paid, fee, credit)


def test_fee_and_credit_always_add_back_to_what_was_paid():
    for paid in (100, 101, 333, 999, 12_345, 500_000):
        s = deposit_fee.split(paid, 3)
        assert round(s["fee"] + s["credit"], 2) == paid


def test_zero_percent_means_no_fee_and_the_old_description():
    assert deposit_fee.split(1000, 0)["credit"] == 1000
    assert deposit_fee.describe(1000, 0) == "Paystack wallet funding"


def test_fee_never_exceeds_the_deposit_and_negative_rates_are_ignored():
    assert deposit_fee.split(100, 500)["credit"] == 0
    assert deposit_fee.split(1000, -5)["fee"] == 0


def test_a_deposit_without_a_marker_is_credited_in_full():
    # Every deposit created before this feature existed looks like this.
    assert deposit_fee.credit_for("Paystack wallet funding", 1000) == 1000
    assert deposit_fee.credit_for(None, 1000) == 1000


def test_the_customer_visible_text_states_paid_and_fee_and_hides_the_markers():
    text = deposit_fee.describe(1000, 3)
    assert text.split(" | ")[0] == "Wallet funding: N1,000 paid, N30 fee"
    assert "deposit_fee_kobo=3000" in text and "credit_kobo=97000" in text


def test_tampered_markers_never_short_change_the_customer():
    # fee + credit must equal what was paid; otherwise fall back to the full amount.
    assert deposit_fee.credit_for("x | deposit_fee_kobo=3000 | credit_kobo=999999", 1000) == 1000


# -------------------------------------------------------------- full flow

class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload, self.status_code = payload, status_code

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _paystack_and_cleanup(monkeypatch):
    monkeypatch.setattr(settings, "paystack_secret_key", "sk_test_not_real")
    monkeypatch.setattr(settings, "deposit_fee_percent", 3.0)
    state = SimpleNamespace(paid_amount_override=None)

    async def fake_paystack(path, method="GET", payload=None):
        if path.endswith("/transaction/initialize"):
            return FakeResponse({"status": True, "data": {
                "reference": payload["reference"], "authorization_url": "https://paystack.test/pay",
                "access_code": "ac"}})
        reference = path.rsplit("/", 1)[-1]
        with db_session() as db:
            tx = q(db, "SELECT user_id,amount FROM transactions WHERE reference=:r", {"r": reference}).mappings().first()
        kobo = state.paid_amount_override if state.paid_amount_override is not None else round(float(tx["amount"]) * 100)
        return FakeResponse({"status": True, "data": {
            "status": "success", "currency": "NGN", "amount": kobo, "reference": reference,
            "metadata": {"user_id": str(tx["user_id"])}}})

    monkeypatch.setattr(main, "paystack", fake_paystack)
    yield state
    with db_session() as db:
        q(db, "DELETE FROM transactions WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'depfee-%@example.com')")
        q(db, "DELETE FROM users WHERE email LIKE 'depfee-%@example.com'")


def _account(client):
    suffix = secrets.token_hex(4)
    response = client.post("/api/register", json={
        "name": "Dep Fee", "email": f"depfee-{suffix}@example.com",
        "phone": f"080{int(suffix, 16) % 10**8:08d}", "password": "password123"})
    assert response.status_code == 200, response.text
    return response.json()["user"]["id"]


def _balance(user_id):
    with db_session() as db:
        return float(q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar())


def _fund(client, amount):
    response = client.post("/api/fund-wallet", json={"amount": amount})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_public_rate_endpoint_reports_the_configured_percent():
    with TestClient(main.app) as client:
        assert client.get("/api/deposit-fee").json() == {"success": True, "percent": 3.0}


def test_paying_1000_credits_970_and_the_response_says_so():
    with TestClient(main.app) as client:
        user = _account(client)
        started = _fund(client, 1000)
        assert (started["fee"], started["credit"]) == (30.0, 970.0)
        verified = client.post("/api/fund-wallet/verify", json={"reference": started["reference"]}).json()
        assert verified["success"] and verified["balance"] == 970.0
        assert (verified["amount"], verified["fee"], verified["credited"]) == (1000.0, 30.0, 970.0)
        assert _balance(user) == 970.0


def test_paystack_is_still_asked_for_the_full_amount_and_validated_against_it(_paystack_and_cleanup):
    with TestClient(main.app) as client:
        user = _account(client)
        started = _fund(client, 2000)
        # Paystack reports a different amount than was created: must be refused, wallet untouched.
        _paystack_and_cleanup.paid_amount_override = 194000  # N1,940: the credit figure, NOT what was charged
        refused = client.post("/api/fund-wallet/verify", json={"reference": started["reference"]})
        assert refused.status_code == 400
        assert _balance(user) == 0.0


def test_the_wallet_row_shows_what_was_paid_and_the_fee_to_the_customer():
    with TestClient(main.app) as client:
        user = _account(client)
        started = _fund(client, 1000)
        client.post("/api/fund-wallet/verify", json={"reference": started["reference"]})
        rows = client.get(f"/api/transactions/{user}").json()["transactions"]
        funding = next(t for t in rows if t["type"] == "wallet_funding")
        assert funding["amount"] == 1000 and funding["status"] == "successful"
        assert funding["description"].split(" | ")[0] == "Wallet funding: N1,000 paid, N30 fee"


def test_verify_and_webhook_together_credit_exactly_once():
    with TestClient(main.app) as client:
        user = _account(client)
        started = _fund(client, 1000)
        reference = started["reference"]
        body = json.dumps({"event": "charge.success", "data": {
            "status": "success", "currency": "NGN", "amount": 100000, "reference": reference,
            "metadata": {"user_id": str(user)}}}).encode()
        signature = hmac.new(b"sk_test_not_real", body, hashlib.sha512).hexdigest()
        hook = client.post("/api/paystack/webhook", content=body, headers={"x-paystack-signature": signature})
        assert hook.status_code == 200
        client.post("/api/fund-wallet/verify", json={"reference": reference})
        client.post("/api/paystack/webhook", content=body, headers={"x-paystack-signature": signature})
        assert _balance(user) == 970.0, "a second confirmation must never credit again"


def test_changing_the_rate_does_not_change_a_deposit_already_in_flight(monkeypatch):
    with TestClient(main.app) as client:
        user = _account(client)
        started = _fund(client, 1000)               # created while the rate is 3%
        monkeypatch.setattr(settings, "deposit_fee_percent", 10.0)   # rate changes before it confirms
        client.post("/api/fund-wallet/verify", json={"reference": started["reference"]})
        assert _balance(user) == 970.0, "the fee fixed at creation must be the one applied"


def test_a_deposit_created_before_the_feature_is_credited_in_full():
    with TestClient(main.app) as client:
        user = _account(client)
        reference = "CD-legacy-" + secrets.token_hex(4)
        with db_session() as db:
            q(db, "INSERT INTO transactions(user_id,type,amount,status,reference,description) "
                  "VALUES(:u,'wallet_funding',1000,'pending',:r,'Paystack wallet funding')", {"u": user, "r": reference})
        verified = client.post("/api/fund-wallet/verify", json={"reference": reference}).json()
        assert verified["success"] and _balance(user) == 1000.0
        assert verified["fee"] == 0.0 and verified["credited"] == 1000.0


def test_with_the_fee_switched_off_the_wallet_gets_everything(monkeypatch):
    monkeypatch.setattr(settings, "deposit_fee_percent", 0.0)
    with TestClient(main.app) as client:
        user = _account(client)
        started = _fund(client, 1000)
        assert (started["fee"], started["credit"]) == (0.0, 1000.0)
        client.post("/api/fund-wallet/verify", json={"reference": started["reference"]})
        assert _balance(user) == 1000.0


def test_amount_limits_are_unchanged():
    with TestClient(main.app) as client:
        _account(client)
        assert client.post("/api/fund-wallet", json={"amount": 99}).status_code == 400
        assert client.post("/api/fund-wallet", json={"amount": 500001}).status_code == 400
        assert client.post("/api/fund-wallet", json={"amount": 100.5}).status_code == 400


# ------------------------------------------------------------ wallet screens

import shutil
import subprocess
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
NODE = shutil.which("node")


def _breakdown(transaction):
    script = ("const s=require(process.argv[1]);"
              "process.stdout.write(JSON.stringify(s.depositBreakdown(JSON.parse(process.argv[2]))));")
    out = subprocess.run([NODE, "-e", script, str(WEB / "statement.js"), json.dumps(transaction)],
                         capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_wallet_reads_the_fee_back_from_a_stored_deposit():
    stored = deposit_fee.describe(1000, 3)
    assert _breakdown({"amount": 1000, "description": stored}) == {"fee": 30, "credited": 970, "hasFee": True}


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_wallet_shows_no_fee_for_old_and_tampered_deposits():
    old = {"fee": 0, "credited": 1000, "hasFee": False}
    assert _breakdown({"amount": 1000, "description": "Paystack wallet funding credited"}) == old
    assert _breakdown({"amount": 1000, "description": "x | deposit_fee_kobo=3000 | credit_kobo=5"}) == old


def test_customers_never_see_the_machine_markers():
    from_python = deposit_fee.describe(1000, 3)
    assert " | " in from_python
    assert from_python.split(" | ")[0] == "Wallet funding: N1,000 paid, N30 fee"
    wallet = (WEB / "wallet.html").read_text()
    assert "customerDescription" in wallet and "feeRows" in wallet


def test_the_fund_page_previews_the_fee_from_the_servers_rate():
    page = (WEB / "fund-wallet.html").read_text()
    for needle in ('id="feeBreakdown"', "/api/deposit-fee", "renderFee", "Added to your wallet",
                   "Math.round(depositFeePercent * 1000)"):
        assert needle in page, needle
    # The browser must still send the FULL typed amount; the fee is the server's job.
    assert "body: JSON.stringify({ amount: amount })" in page


# ---- The fee must be impossible to miss BEFORE paying -----------------------
# A customer paid and saw no warning that 3% is deducted. The old page only
# showed the fee after a background fetch succeeded, and let the button go
# straight to Paystack. These pin the page-level guarantees.

def _fund_page():
    from pathlib import Path
    return (Path(__file__).resolve().parents[3] / "apps" / "web" / "fund-wallet.html").read_text(encoding="utf-8")


def test_fund_page_has_a_permanent_fee_notice_near_the_top():
    page = _fund_page()
    assert 'id="feeNotice"' in page
    # It sits above the form, so it is read before the amount box.
    assert page.index('id="feeNotice"') < page.index('id="fundForm"')
    # It is not behind the .hidden class, so it can never be silently absent.
    assert 'class="fee-notice" id="feeNotice"' in page


def test_pay_button_waits_for_the_fee_and_never_stays_dead():
    page = _fund_page()
    assert 'id="fundButton" disabled>Loading fee' in page, "button must start disabled until the fee is known"
    assert "Retry loading fee" in page, "a failed fee load must offer a retry, not a dead or pay button"
    assert "attempt < 2" in page, "a cold-starting API gets a second chance"
    # When the fee cannot be loaded the notice still warns that a fee exists.
    assert "could not load the exact amount" in page


def test_customer_confirms_exact_amounts_before_leaving_for_paystack():
    page = _fund_page()
    submit = page[page.index('fundForm.addEventListener("submit"'):]
    confirm_at = submit.index("MELODEXS_UI.confirm(")
    fetch_at = submit.index('fetch("/api/fund-wallet"')
    assert confirm_at < fetch_at, "the confirmation must come before the payment request"
    for needle in ("You pay", "Deposit fee (", "Added to your wallet"):
        assert needle in submit[:fetch_at]
    assert "if (!agreed) return;" in submit[:fetch_at], "declining must stop the payment"


def test_confirmation_dialog_keeps_line_breaks():
    from pathlib import Path
    css = (Path(__file__).resolve().parents[3] / "apps" / "web" / "styles.css").read_text(encoding="utf-8")
    assert "#confirm-message { white-space: pre-line; }" in css
