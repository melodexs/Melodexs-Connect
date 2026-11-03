"""The public price list must show real prices, safely, to logged-out visitors."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
PAGE = (WEB / "prices.html").read_text()


def test_price_list_reads_only_the_public_catalog_endpoint():
    """No account data may ever reach a logged-out page."""
    calls = set(re.findall(r'fetch\("([^"]+)"', PAGE))
    assert calls == {"/api/data-plans"}, calls


def test_price_list_does_not_depend_on_the_login_session():
    assert "localStorage" not in PAGE and "sessionStorage" not in PAGE
    assert "melodexs_session" not in PAGE and "Authorization" not in PAGE
    assert "ui.js" not in PAGE, "ui.js boots a session and redirects logged-out visitors"


def test_every_dynamic_value_is_escaped_before_it_reaches_innerHTML():
    """Plan names come from a supplier feed, so they are untrusted text."""
    assert "function esc(" in PAGE
    # the category is rendered through the grouping key, so it is escaped as `cat`
    for expr in ("esc(p.plan)", "esc(p.validity)", "esc(cat)", "esc(n)"):
        assert expr in PAGE, f"{expr} must wrap every value written into innerHTML"
    assert "esc(naira(p.selling_price))" in PAGE


def test_no_raw_plan_field_is_concatenated_into_markup():
    """Every `innerHTML` assignment may only take plan fields through esc().

    The search filter also joins p.plan + p.category, but that builds a string to
    compare against and is never written to the page, so it is excluded.
    """
    render = PAGE[PAGE.index("function renderList"):PAGE.index('document.getElementById("netTabs").addEventListener')]
    markup_lines = [ln for ln in render.splitlines() if "<" in ln and "innerHTML" not in ln or "+ p." in ln and "<" in ln]
    for ln in markup_lines:
        for m in re.finditer(r"\+\s*(p\.\w+)", ln):
            before = ln[:m.start()].rstrip()
            assert before.endswith("esc("), f"unescaped {m.group(1)} in markup: {ln.strip()}"


def test_price_list_lets_visitors_sign_up_and_get_help():
    assert 'href="/register.html"' in PAGE
    assert 'href="/help.html"' in PAGE


def test_price_list_handles_empty_and_failed_loads():
    assert "No plans available" in PAGE
    assert "No plans match your search" in PAGE
    assert ".catch(" in PAGE, "a failed request must show a message, not a blank page"


def test_network_tabs_are_keyboard_and_screen_reader_friendly():
    assert 'aria-pressed' in PAGE and 'aria-label="Choose a network"' in PAGE
    assert 'aria-live="polite"' in PAGE


def test_price_list_is_indexable_and_in_the_sitemap():
    assert "/prices.html" in (WEB / "sitemap.xml").read_text()
    assert "Disallow: /prices.html" not in (WEB / "robots.txt").read_text()
    assert '<meta name="description"' in PAGE


def test_landing_page_links_to_the_price_list():
    assert 'href="/prices.html"' in (WEB / "index.html").read_text()
