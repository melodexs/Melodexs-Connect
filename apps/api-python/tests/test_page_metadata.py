"""Every page carries a description, and private pages stay out of search.

robots.txt only stops crawling; a blocked URL can still be listed in results if
something links to it. A noindex tag on the page is what actually keeps account
and money pages out, so the two are pinned together here.
"""
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
PAGES = sorted(p for p in WEB.glob("*.html"))
SITEMAP = (WEB / "sitemap.xml").read_text()
def _page_for(url):
    path = urlparse(url).path.strip("/")
    return path or "index.html"   # the bare site URL is the landing page


LISTED = {_page_for(u) for u in re.findall(r"<loc>([^<]+)</loc>", SITEMAP)}


def meta(page, name):
    m = re.search(rf'<meta name="{name}" content="([^"]*)"', page.read_text())
    return m.group(1) if m else None


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_page_has_a_useful_description(page):
    text = meta(page, "description")
    assert text, f"{page.name} has no meta description"
    assert 20 <= len(text) <= 200, f"{page.name} description is {len(text)} characters"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_pages_in_the_sitemap_are_indexable_and_the_rest_are_not(page):
    robots = meta(page, "robots") or ""
    if page.name in LISTED:
        assert "noindex" not in robots, f"{page.name} is in the sitemap but marked noindex"
    else:
        assert "noindex" in robots, f"{page.name} is not in the sitemap and must be noindex"


def test_descriptions_are_not_copy_pasted_between_pages():
    seen = {}
    for page in PAGES:
        text = meta(page, "description")
        assert text not in seen, f"{page.name} repeats {seen[text]}'s description"
        seen[text] = page.name
