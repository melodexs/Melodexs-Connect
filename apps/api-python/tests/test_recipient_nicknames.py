"""Saved recipients can be given a name ("Mum"), not just stored as a number.

The backend always accepted a label; the pages saved an empty one. These tests
pin the prompt flow and the scope of `ui` on each page (buy-data holds the UI
object, buy-airtime holds a getter function; mixing them up throws on tap).
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
UI_JS = (WEB / "ui.js").read_text()
AIRTIME = (WEB / "buy-airtime.html").read_text()
DATA = (WEB / "buy-data.html").read_text()


def save_favorite_body(page):
    start = page.index("async function saveFavorite()")
    end = page.index("\n}\n", start)
    return page[start:end]


def test_ui_exposes_a_self_building_text_prompt():
    assert "UI.promptText = function" in UI_JS
    body = UI_JS[UI_JS.index("UI.promptText = function"):UI_JS.index("/* ---------- HTML escaping")]
    assert 'createElement("div")' in body, "must build its own markup; pages must not need to ship it"
    assert 'id = "prompt-modal"' in body
    assert "aria-modal" in body and "aria-labelledby" in body


def test_prompt_distinguishes_cancel_skip_and_save():
    body = UI_JS[UI_JS.index("UI.promptText = function"):UI_JS.index("/* ---------- HTML escaping")]
    assert "done(null)" in body, "cancel must resolve null"
    assert 'done("")' in body, "skip must resolve an empty string"
    assert "input.value.trim()" in body, "save must resolve trimmed text"


def test_prompt_supports_keyboard_use():
    body = UI_JS[UI_JS.index("UI.promptText = function"):UI_JS.index("/* ---------- HTML escaping")]
    assert '"Enter"' in body and '"Escape"' in body
    assert "input.focus()" in body
    # Escape must work even when focus has moved to <body> (user tapped the card text)
    assert 'document.addEventListener("keydown", onKey, true)' in body
    assert "input.onkeydown" not in body and "backdrop.onkeydown" not in body


def test_prompt_cleans_up_its_handlers_between_uses():
    body = UI_JS[UI_JS.index("UI.promptText = function"):UI_JS.index("/* ---------- HTML escaping")]
    assert "ok.onclick = skip.onclick = cancel.onclick = backdrop.onclick = null" in body
    # the document-level key listener must be removed on close, or they stack up
    assert 'document.removeEventListener("keydown", onKey, true)' in body


def test_prompt_never_writes_user_text_as_html():
    body = UI_JS[UI_JS.index("UI.promptText = function"):UI_JS.index("/* ---------- HTML escaping")]
    # title and message are caller-supplied; they must be set as text
    assert 'getElementById("prompt-title").textContent' in body
    assert 'getElementById("prompt-message").textContent' in body


def test_both_pages_ask_for_a_name_before_saving():
    for name, page in (("buy-airtime", AIRTIME), ("buy-data", DATA)):
        body = save_favorite_body(page)
        assert "promptText(" in body, f"{name} should ask for a name"
        assert "label: nickname" in body, f"{name} should send the name, not an empty label"
        assert 'label: ""' not in body, f"{name} still saves an empty label"


def test_cancelling_the_prompt_saves_nothing():
    for name, page in (("buy-airtime", AIRTIME), ("buy-data", DATA)):
        body = save_favorite_body(page)
        assert "if (nickname === null) return;" in body, f"{name} must stop on cancel"
        # the cancel check has to come before the network call
        assert body.index("nickname === null") < body.index('fetch("/api/favorites"'), name


def test_ui_is_reached_the_right_way_on_each_page():
    """buy-airtime: `const ui = () => ...` (call it). buy-data: `const ui = UI()` (use it)."""
    air = save_favorite_body(AIRTIME)
    assert "ui().promptText(" in air and "ui.promptText(" not in air
    assert "const ui = () => window.MELODEXS_UI;" in AIRTIME

    dat = save_favorite_body(DATA)
    assert "const ui = UI();" in dat
    assert "ui.promptText(" in dat and "ui().promptText(" not in dat, (
        "buy-data holds the UI object itself; calling it as a function throws on tap")


def test_chips_show_the_name_and_fall_back_to_the_number():
    for name, page in (("buy-airtime", AIRTIME), ("buy-data", DATA)):
        assert "fav.label || fav.phone" in page, f"{name} chip should prefer the nickname"
