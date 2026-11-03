"""Every page must load the shared shell.

A page missing api.js silently loses the /api rewrite (every fetch 404s) and one
missing ui.js renders without navigation. Both have happened, so this walks the
real files rather than trusting a template.
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"

# Logged-in pages that must carry the full app shell (chrome + API bridge).
APP_PAGES = {
    "dashboard.html", "wallet.html", "buy-data.html", "buy-airtime.html",
    "buy-electricity.html", "buy-cable.html", "buy-education.html",
    "fund-wallet.html", "purchase-pin.html",
}
# Public and standalone pages: they keep the design system but not the shell.
# offline.html is self-contained by design; admin.html ships its own styles.
NO_SHELL = {"offline.html", "create-pin.html", "change-pin.html", "admin.html", "privacy.html", "help.html", "prices.html",
            "index.html", "login.html", "register.html", "forgot-password.html", "reset-password.html"}

REQUIRED_SCRIPTS = ("api.js", "ui.js")


def _pages():
    return sorted(WEB.glob("*.html"))


def test_app_pages_load_the_shared_scripts():
    """Without api.js every /api call 404s; without ui.js the page has no nav."""
    missing = {}
    for page in _pages():
        if page.name not in APP_PAGES:
            continue
        text = page.read_text(errors="ignore")
        absent = [s for s in REQUIRED_SCRIPTS if s not in text]
        if absent:
            missing[page.name] = absent
    assert not missing, f"app pages without the shared scripts: {missing}"


def test_the_shell_pages_are_all_present():
    """Guards the inventory above: a new app page must be added deliberately."""
    found = {p.name for p in _pages()}
    assert APP_PAGES <= found, f"declared app pages that do not exist: {APP_PAGES - found}"
    assert not (APP_PAGES & NO_SHELL), "a page cannot be both app and public"


def test_pages_that_are_not_app_pages_avoid_the_shell():
    """Public pages must not pull the chrome: it would render a nav to pages
    the visitor cannot open."""
    leaking = [p.name for p in _pages()
               if p.name in NO_SHELL and "ui.js" in p.read_text(errors="ignore")]
    assert not leaking, f"public pages loading the app chrome: {leaking}"


def test_every_page_loads_the_stylesheet():
    # offline.html is deliberately self-contained (inline styles, no requests);
    # admin.html ships its own stylesheet.
    standalone = {"offline.html", "admin.html"}
    missing = [p.name for p in _pages()
               if p.name not in standalone and "styles.css" not in p.read_text(errors="ignore")]
    assert not missing, f"pages without styles.css: {missing}"


def test_every_page_declares_a_title_and_viewport():
    problems = {}
    for page in _pages():
        text = page.read_text(errors="ignore")
        if not re.search(r"<title>[^<]{3,}</title>", text, re.I):
            problems.setdefault(page.name, []).append("title")
        if 'name="viewport"' not in text:
            problems.setdefault(page.name, []).append("viewport")
    assert not problems, f"pages missing metadata: {problems}"


def test_referenced_local_assets_exist():
    """A typo in a src/href is invisible until a user hits it."""
    pattern = re.compile(r'(?:src|href)="(/[^"?]+\.(?:js|css|png|jpg|jpeg|svg|webp|ico))"')
    broken = {}
    for page in _pages():
        for asset in pattern.findall(page.read_text(errors="ignore")):
            if not (WEB / asset.lstrip("/")).exists():
                broken.setdefault(page.name, []).append(asset)
    assert not broken, f"missing local assets: {broken}"
