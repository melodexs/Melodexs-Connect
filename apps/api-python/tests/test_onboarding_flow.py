"""First-time setup: create account -> create PIN -> add profile picture -> home.

A brand-new account is flagged at registration (cheapdataNewUserId). After the
PIN is created the Profile page shows an "Add a profile picture" step; adding a
photo or skipping both land on the home page. Returning users are never sent
through it. These tests pin the wiring; the browser walk-through is in the PR.
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
PROFILE = (WEB / "purchase-pin.html").read_text()
REGISTER = (WEB / "register.html").read_text()


def test_registration_flags_the_account_as_new_and_goes_to_the_profile_page():
    assert 'localStorage.setItem("cheapdataNewUserId"' in REGISTER
    assert '"/purchase-pin.html"' in REGISTER


def test_register_form_normalises_plus234_before_validating():
    assert "function normalizePhone" in REGISTER
    assert '"+234"' in REGISTER
    submit = REGISTER[REGISTER.index('form.addEventListener("submit"'):]
    assert submit.index("normalizePhone(") < submit.index("test(phone)"), "must normalise before validating"
    field = REGISTER[REGISTER.index('id="phone"'):REGISTER.index('id="phone"') + 200]
    assert "+234" in field, "placeholder should show the +234 form"


def test_photo_step_exists_and_is_hidden_until_the_pin_is_created():
    tag = re.search(r'<section[^>]*id="photoStep"[^>]*>', PROFILE).group(0)
    assert "hidden" in tag
    for needle in ('id="photoStepInput"', 'id="photoStepSkip"', 'id="photoStepChoose"'):
        assert needle in PROFILE


def test_creating_a_pin_shows_the_photo_step_only_for_new_accounts():
    block = PROFILE[PROFILE.index('fetch("/api/purchase-pin/set"'):PROFILE.index('document.getElementById("changePinForm")')]
    assert "isNewAccount()" in block and "showPhotoStep()" in block
    assert "loadUser()" in block, "returning users keep the normal reload"


def test_photo_or_skip_both_finish_on_the_home_page_and_clear_the_flag():
    finish = PROFILE[PROFILE.index("function finishOnboarding"):PROFILE.index("function showPhotoStep")]
    assert 'removeItem("cheapdataNewUserId")' in finish
    assert 'window.location.href = "dashboard.html"' in finish
    assert 'getElementById("photoStepSkip").addEventListener("click", finishOnboarding)' in PROFILE
    assert "finishOnboarding, 900" in PROFILE


def test_a_failed_upload_does_not_strand_the_user():
    handler = PROFILE[PROFILE.index('getElementById("photoStepInput").addEventListener'):PROFILE.index('getElementById("photoStepSkip").addEventListener')]
    assert "const ok = await uploadAvatar(file)" in handler
    assert "skip.disabled = false" in handler, "Skip must be usable again after a failure"
    upload = PROFILE[PROFILE.index("async function uploadAvatar"):PROFILE.index("async function removeAvatar")]
    assert "return true" in upload and "return false" in upload


def test_a_stale_flag_is_cleared_once_a_pin_exists():
    load = PROFILE[PROFILE.index("async function loadUser"):PROFILE.index('document.getElementById("setPinForm")')]
    assert 'removeItem("cheapdataNewUserId")' in load
