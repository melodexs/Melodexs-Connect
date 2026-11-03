"""iOS has no install prompt, so the metas are the install experience.

Without them a home-screen shortcut opens like a bookmark with a browser chrome,
and the status bar overlaps the navigation.
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
APP_PAGES = [p for p in WEB.glob("*.html")
             if p.name not in {"offline.html", "admin.html", "create-pin.html", "change-pin.html"}]


def test_every_page_opts_into_the_standalone_app():
    missing = [p.name for p in APP_PAGES
               if 'name="apple-mobile-web-app-capable"' not in p.read_text(errors="ignore")
               and 'name="mobile-web-app-capable"' not in p.read_text(errors="ignore")]
    assert not missing, f"pages that open as a bookmark on iOS: {missing}"


def test_every_page_declares_a_home_screen_title():
    missing = [p.name for p in APP_PAGES
               if "apple-mobile-web-app-title" not in p.read_text(errors="ignore")]
    assert not missing, f"pages without a home-screen title: {missing}"


def test_every_page_references_an_existing_touch_icon():
    problems = {}
    for page in APP_PAGES:
        text = page.read_text(errors="ignore")
        match = re.search(r'apple-touch-icon"\s+href="(/[^"]+)"', text)
        if not match:
            problems.setdefault(page.name, []).append("no apple-touch-icon")
            continue
        if not (WEB / match.group(1).lstrip("/")).exists():
            problems.setdefault(page.name, []).append(match.group(1))
    assert not problems, f"broken touch icons: {problems}"
