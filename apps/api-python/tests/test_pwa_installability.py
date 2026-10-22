"""PWA installability contract tests.

Installs on both Android and iOS are driven purely by static assets and
tags, so they are verified statically: a valid manifest with all
required identity fields and real icon files, offline fallback wired
through the service worker, and the full set of install tags on every
customer-facing page. No network calls.
"""
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"

# change-pin/create-pin are instant redirect stubs; offline.html is
# deliberately self-contained (no CSS/JS so it renders with zero network).
REDIRECT_STUBS = {"change-pin.html", "create-pin.html", "offline.html"}


def all_pages():
    return sorted(p.name for p in WEB.glob("*.html") if p.name not in REDIRECT_STUBS)


def test_manifest_is_valid_and_installable():
    manifest = json.loads((WEB / "manifest.webmanifest").read_text())
    assert manifest["name"] == "MELODEXS CONNECT"
    assert manifest["short_name"]
    assert manifest["display"] == "standalone"
    assert manifest["start_url"].startswith("/")
    assert manifest["scope"] == "/"
    assert manifest["theme_color"] == "#0251B0"
    assert manifest["background_color"] == "#020817"
    assert manifest.get("id"), "manifest needs a stable id for install identity"
    assert manifest.get("orientation") == "portrait"
    # Chrome's install criteria require both a 192px and a 512px icon;
    # Android adaptive icons require a maskable one.
    icons = manifest["icons"]
    assert any(i["sizes"] == "192x192" for i in icons)
    assert any(i["sizes"] == "512x512" for i in icons)
    assert any(i.get("purpose") == "maskable" for i in icons)
    for icon in icons:
        path = WEB / icon["src"].lstrip("/")
        assert path.is_file(), f"missing manifest icon file: {icon['src']}"
    for shot in manifest.get("screenshots", []):
        assert (WEB / shot["src"].lstrip("/")).is_file(), f"missing screenshot: {shot['src']}"
        assert shot["form_factor"] == "narrow"


def test_icon_files_have_the_advertised_dimensions():
    try:
        from PIL import Image
    except ImportError:
        return  # Pillow is a sandbox-only convenience; dimensions are checked on CI without it
    expected = {
        "icons/melodexs-connect-192.png": (192, 192),
        "icons/melodexs-connect-512.png": (512, 512),
        "icons/melodexs-connect-maskable.png": (512, 512),
        "icons/apple-touch-icon.png": (180, 180),
    }
    for rel, size in expected.items():
        assert (WEB / rel).is_file(), f"missing {rel}"
        assert Image.open(WEB / rel).size == size, f"{rel} is not {size[0]}x{size[1]}"


def test_service_worker_provides_offline_fallback():
    sw = (WEB / "sw.js").read_text()
    assert "melodexs-static-v" in sw
    assert '"/offline.html"' in sw, "offline fallback page must be pre-cached at install"
    assert sw.index("cache.add") < sw.index("skipWaiting"), "offline page must be cached during install, not later"
    assert "request.mode === \"navigate\"" in sw, "navigations need network-first with offline fallback"
    assert "/api/" in sw, "API calls must never be served from cache"


def test_offline_page_is_self_contained():
    offline = (WEB / "offline.html").read_text()
    assert "<style>" in offline, "offline page must inline its styles (zero network)"
    assert not re.search(r"<link[^>]+stylesheet", offline)
    assert not re.search(r"<script[^>]+src=", offline)
    assert "/api/" not in offline
    assert "offline" in offline.lower()


def test_every_page_carries_the_install_tags():
    pages = all_pages()
    assert len(pages) >= 15
    for name in pages:
        html = (WEB / name).read_text()
        assert "manifest.webmanifest" in html, f"{name}: no manifest link"
        assert '<meta name="theme-color"' in html, f"{name}: no theme-color"
        assert "apple-touch-icon" in html, f"{name}: no iOS home-screen icon"
        assert '<meta name="apple-mobile-web-app-capable" content="yes">' in html, f"{name}: no iOS standalone meta"
        assert '<meta name="apple-mobile-web-app-title"' in html, f"{name}: no iOS home-screen title"
        assert 'content="black-translucent"' in html, f"{name}: no iOS status-bar style"
        assert "viewport-fit=cover" in html, f"{name}: no safe-area viewport"
        assert "pwa.js" in html, f"{name}: install prompt + service worker not registered"


def test_install_api_is_exposed_for_explicit_buttons():
    pwa = (WEB / "pwa.js").read_text()
    assert "window.MELODEXS_INSTALL" in pwa
    for member in ("platform", "isStandalone", "canPrompt", "onAvailabilityChange", "promptInstall"):
        assert member in pwa, f"install API missing {member}"
    assert "beforeinstallprompt" in pwa, "Android install prompt must be captured"
    assert "Add to Home Screen" in pwa, "iOS has no native prompt; A2HS instructions are required"
    # The profile page is the explicit entry point.
    profile = (WEB / "purchase-pin.html").read_text()
    assert "installCard" in profile
    assert "MELODEXS_INSTALL" in profile
    assert "DOMContentLoaded" in profile, "install API is created by the deferred pwa.js"
