"""Every form control is nameable, and password fields tell managers what they are.

A placeholder disappears once someone types and is not reliably announced by a
screen reader, so each control needs a real label: a wrapping <label>, a
<label for>, or an aria-label.
"""
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
PAGES = sorted(WEB.glob("*.html"))
SKIP_TYPES = {"hidden", "checkbox", "radio", "file", "submit", "button"}


def controls_without_a_name(html):
    labelled_ids = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', html))
    wrapped = [m.group(0) for m in re.finditer(r"<label\b[^>]*>.*?</label>", html, re.S)]
    problems = []
    for m in re.finditer(r"<input\b([^>]*)>", html):
        attrs = m.group(1)
        kind = (re.search(r'type="([^"]+)"', attrs) or [None, "text"])[1]
        if kind in SKIP_TYPES or "aria-label" in attrs or "aria-labelledby" in attrs:
            continue
        ident = re.search(r'\bid="([^"]+)"', attrs)
        if ident and ident.group(1) in labelled_ids:
            continue
        if any(m.group(0) in block for block in wrapped):
            continue
        problems.append(attrs.strip()[:70])
    return problems


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_text_input_has_an_accessible_name(page):
    assert controls_without_a_name(page.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_password_field_declares_what_it_is_for(page):
    html = page.read_text(encoding="utf-8")
    for m in re.finditer(r"<input\b([^>]*type=\"password\"[^>]*)>", html):
        attrs = m.group(1)
        if 'id="purchasePin"' in attrs:
            # The PIN that authorises spending is deliberately never saved or
            # autofilled by the browser.
            assert 'autocomplete="off"' in attrs, (page.name, attrs[:80])
        else:
            assert re.search(r'autocomplete="(current-password|new-password)"', attrs), (page.name, attrs[:80])


def test_the_checker_itself_catches_a_bare_input():
    assert controls_without_a_name('<input id="x" placeholder="Name">') != []
    assert controls_without_a_name('<input id="x" aria-label="Name">') == []
    assert controls_without_a_name('<label for="x">Name</label><input id="x">') == []
    assert controls_without_a_name('<label>Name <input id="x"></label>') == []
