"""Password hashing, bearer-token parsing and the Paystack signature check."""
import hashlib
import hmac

import pytest

from app import security


class _Req:
    def __init__(self, cookies=None, headers=None):
        self.cookies = cookies or {}
        self.headers = headers or {}


def test_password_hash_verifies_and_is_salted():
    first, second = security.password_hash("correct horse"), security.password_hash("correct horse")
    assert first != second, "two hashes of the same password must differ (salted)"
    assert security.password_check("correct horse", first)
    assert not security.password_check("wrong horse", first)


# A missing PIN is refused with a clean 400 by every caller before password_check
# is reached, so None never arrives here; only malformed stored text can.
@pytest.mark.parametrize("stored", ["", "not-a-bcrypt-hash"])
def test_a_malformed_stored_hash_is_a_failed_check_not_a_crash(stored):
    assert security.password_check("anything", stored) is False


def test_the_session_cookie_is_read_and_a_forged_one_is_rejected():
    token = security.serializer.dumps("sid-123")
    assert security.session_id(_Req(cookies={security.COOKIE: token})) == "sid-123"
    assert security.session_id(_Req(cookies={security.COOKIE: token + "x"})) is None
    assert security.session_id(_Req()) is None


def test_a_bearer_token_is_accepted_only_when_there_is_no_cookie():
    good, other = security.serializer.dumps("from-header"), security.serializer.dumps("from-cookie")
    assert security.session_id(_Req(headers={"authorization": f"Bearer {good}"})) == "from-header"
    assert security.session_id(_Req(headers={"authorization": f"bearer  {good}  "})) == "from-header"
    both = _Req(cookies={security.COOKIE: other}, headers={"authorization": f"Bearer {good}"})
    assert security.session_id(both) == "from-cookie"


@pytest.mark.parametrize("header", ["Bearer", "Basic abc", "Bearer not-a-signed-token", ""])
def test_malformed_authorization_headers_do_not_authenticate(header):
    assert security.session_id(_Req(headers={"authorization": header})) is None


def test_paystack_signature_is_hmac_sha512_of_the_raw_body():
    body, secret = b'{"event":"charge.success"}', "sk_test_x"
    good = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    assert security.valid_paystack_signature(secret, body, good)
    assert not security.valid_paystack_signature(secret, body + b" ", good), "a changed body must fail"
    assert not security.valid_paystack_signature("other", body, good)


@pytest.mark.parametrize("secret,received", [(None, "abc"), ("", "abc"), ("sk", None), ("sk", "")])
def test_missing_secret_or_signature_never_validates(secret, received):
    assert security.valid_paystack_signature(secret, b"{}", received) is False
