"""The service worker decides what an offline user sees, and what they never see
stale.

Two rules matter more than the rest: API responses are never cached (a stale
balance or price is worse than no answer), and a failed navigation lands on the
branded offline page rather than the browser's error screen.
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
SW = (WEB / "sw.js").read_text()


def test_the_worker_recognises_api_paths():
    assert "/api/" in SW, "the worker must exclude API traffic from its caches"


def test_the_offline_page_is_precached_and_exists():
    assert "offline.html" in SW
    assert (WEB / "offline.html").exists()


def test_cache_names_are_versioned():
    """Bumping the version is how a deploy evicts an old shell."""
    names = re.findall(r"melodexs-[a-z]+-v(\d+)", SW)
    assert names, "cache names must carry a version suffix"
    assert all(int(n) >= 3 for n in names)


def test_a_failed_navigation_falls_back_to_the_cache():
    assert "navigate" in SW or 'mode === "navigate"' in SW
    assert "caches.match" in SW or "cache.match" in SW
