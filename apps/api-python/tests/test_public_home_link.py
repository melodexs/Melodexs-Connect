"""'Back to home' on the public pages must take a signed-in customer to the
dashboard, not the welcome page.

Help, Prices and Privacy are open to everyone, so their link defaults to the
welcome page ("/"). home-link.js repoints it to /dashboard.html when a saved
sign-in exists. Login and Register keep "/" on purpose: those visitors are
signed out, so the welcome page is the right place for them.
"""
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
PAGES = {"help.html": "help-home", "privacy.html": "policy-home", "prices.html": None}
SCRIPT = (WEB / "home-link.js").read_text()


def page(name):
    return (WEB / name).read_text()


def test_each_public_page_marks_its_home_link_and_loads_the_script():
    for name in PAGES:
        html = page(name)
        assert "data-home-link" in html, f"{name}: home link is not marked"
        assert '<script src="/home-link.js" defer></script>' in html, f"{name}: script missing"


def test_the_marked_link_still_defaults_to_the_welcome_page():
    # Signed-out visitors, blocked storage and no-JS all keep the default.
    for name in PAGES:
        html = page(name)
        start = html.index("data-home-link")
        tag = html[html.rfind("<a", 0, start):html.index(">", start)]
        assert 'href="/"' in tag, f"{name}: default must stay the welcome page"


def test_script_sends_signed_in_users_to_the_dashboard_and_fails_safe():
    assert '"/dashboard.html"' in SCRIPT
    assert "cheapdataToken" in SCRIPT and "cheapdataUser" in SCRIPT
    assert "[data-home-link]" in SCRIPT
    assert "try" in SCRIPT and "catch" in SCRIPT, "blocked storage must not throw"
    assert "if (!signedIn) return" in SCRIPT, "signed-out visitors must be left alone"


def test_login_and_register_keep_the_welcome_page_link():
    for name in ("login.html", "register.html"):
        html = page(name)
        assert 'class="back-home" href="/"' in html
        assert "data-home-link" not in html, f"{name}: signed-out visitors should reach the welcome page"
