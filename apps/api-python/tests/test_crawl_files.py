"""What a crawler is told must match what is published.

robots.txt, the sitemap and the real page list drift apart silently otherwise:
a disallowed landing page loses the site from search, and a sitemap entry for a
deleted page turns into a 404 in the index.
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def test_robots_and_sitemap_agree():
    robots = (WEB / "robots.txt").read_text()
    disallowed = {line.split(":", 1)[1].strip()
                  for line in robots.splitlines() if line.lower().startswith("disallow:")}
    sitemap = (WEB / "sitemap.xml").read_text()
    assert "Sitemap: https://melodexs-connect.onrender.com/sitemap.xml" in robots
    for loc in re.findall(r"<loc>([^<]+)</loc>", sitemap):
        path = loc.split("melodexs-connect.onrender.com", 1)[1] or "/"
        # Compare whole rules: "Disallow: /" must not match "/dashboard.html".
        assert path not in disallowed, f"{path} is in the sitemap but disallowed"


def test_sitemap_entries_exist():
    sitemap = (WEB / "sitemap.xml").read_text()
    for loc in re.findall(r"<loc>([^<]+)</loc>", sitemap):
        path = loc.split("melodexs-connect.onrender.com", 1)[1]
        target = WEB / (path.lstrip("/") or "index.html")
        assert target.exists(), f"sitemap points at a missing page: {path}"


def test_account_pages_are_not_indexable():
    robots = (WEB / "robots.txt").read_text()
    for page in ("/wallet.html", "/dashboard.html", "/purchase-pin.html", "/admin.html"):
        assert f"Disallow: {page}" in robots, f"{page} should not be indexed"


def test_sitemap_is_well_formed():
    sitemap = (WEB / "sitemap.xml").read_text()
    assert sitemap.lstrip().startswith("<?xml")
    assert sitemap.count("<url>") == sitemap.count("</url>") > 0
    assert "http://www.sitemaps.org/schemas/sitemap/0.9" in sitemap
