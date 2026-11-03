"""The desktop shell is a set of CSS guarantees.

If the sidebar shows on a phone it eats the screen; if it hides on a laptop the
app looks like a stretched phone again. If the content is not offset the sidebar
covers it. These are cheap assertions that catch a broken media query.
"""
import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[3] / "apps" / "web" / "styles.css").read_text()


def _block(selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert match, f"{selector} has no rule"
    return match.group(1)


def test_the_sidebar_is_hidden_by_default():
    """Default styles are the phone styles; only the media query reveals it."""
    assert re.search(r"\.app-sidebar\s*\{\s*display:\s*none", CSS), (
        "the sidebar must be display:none outside the desktop breakpoint")


def test_the_sidebar_is_declared_inside_a_900px_breakpoint():
    """Cheap but useful: it must not be switched on at some other width."""
    positions = [m.start() for m in re.finditer(r"@media \(min-width: 900px\)", CSS)]
    assert positions, "the 900px breakpoint is how the desktop shell starts"
    sidebar_at = CSS.index(".app-sidebar {")
    assert any(p < sidebar_at for p in positions), (
        "the sidebar must be declared after a 900px breakpoint")
    wider = [m.start() for m in re.finditer(r"@media \(min-width: (?!900px)(\d+)px\)", CSS)]
    assert all(w > sidebar_at for w in wider), (
        "no other breakpoint may precede the sidebar declaration")


def test_the_sidebar_is_fixed_and_sized():
    # Several rules target .app-sidebar (the hidden default and the desktop one),
    # so inspect the one that actually lays it out.
    blocks = re.findall(r"\.app-sidebar\s*\{([^}]*)\}", CSS)
    desktop = next((b for b in blocks if "position: fixed" in b), None)
    assert desktop, "the desktop sidebar must be position: fixed"
    assert "width: 252px" in desktop
    assert "z-index" in desktop, "the sidebar must sit above page content"


def test_the_page_is_offset_by_the_sidebar_width():
    assert re.search(r"body\.app-body\.has-sidebar\s*\{[^}]*padding-left:\s*252px", CSS), (
        "content must be offset by exactly the sidebar width or it will be covered")


def test_the_redundant_tab_row_is_removed_on_desktop():
    assert re.search(r"body\.has-sidebar\s+\.desktop-tabs\s*\{\s*display:\s*none", CSS)


def test_the_mobile_bottom_bar_is_not_displayed_on_desktop():
    assert re.search(r"\.bottom-nav\s*\{\s*display:\s*none", CSS)
