"""Login, Create account, Forgot and Reset password share one centred column.

Regression: the card and hero had no width of their own, so each sized itself
to its content. Create account (more fields, longer subtitle) stretched across
a whole laptop screen while Login looked fine. They must share one rule.
"""
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
CSS = (WEB / "styles.css").read_text(encoding="utf-8")
AUTH_PAGES = ["login.html", "register.html", "forgot-password.html", "reset-password.html"]


@pytest.mark.parametrize("page", AUTH_PAGES)
def test_auth_pages_use_the_shared_markup(page):
    html = (WEB / page).read_text(encoding="utf-8")
    assert '<body class="auth-body">' in html
    for needed in ('class="landing-nav"', 'class="auth-hero"', 'class="auth-card"'):
        assert needed in html, (page, needed)


def test_nav_hero_and_card_are_pinned_to_the_same_width():
    block = re.search(
        r"body\.auth-body:not\(\.landing\) \.landing-nav,\s*"
        r"body\.auth-body:not\(\.landing\) \.auth-hero,\s*"
        r"body\.auth-body:not\(\.landing\) \.auth-card\s*\{([^}]*)\}", CSS)
    assert block, "nav, hero and card must share one width rule"
    rules = block.group(1)
    assert re.search(r"max-width:\s*\d+px", rules), "a fixed maximum width is what stops the stretch"
    assert "margin-left: auto" in rules and "margin-right: auto" in rules, "the column must be centred"
    assert "width: 100%" in rules, "on a phone the column fills the screen"


def test_the_column_is_not_applied_to_the_landing_page():
    assert "body.auth-body:not(.landing)" in CSS
    landing = (WEB / "index.html").read_text(encoding="utf-8")
    assert "auth-body landing" in landing


def test_the_brand_accent_in_the_headline_is_styled():
    assert re.search(r"\.auth-accent\s*\{\s*color:\s*var\(--lime", CSS)
