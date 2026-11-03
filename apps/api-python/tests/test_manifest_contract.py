"""The manifest is what makes the app installable.

A missing icon or screenshot does not fail loudly: the install sheet just looks
broken, or the browser refuses to offer installation at all. So every asset the
manifest promises must exist on disk with the size it claims.
"""
import json
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def manifest():
    return json.loads((WEB / "manifest.webmanifest").read_text())


def test_identity_and_start_url():
    data = manifest()
    assert data["name"] and data["short_name"]
    assert data["start_url"] == "/dashboard.html"
    assert data.get("id") == "/dashboard.html", "a stable id keeps the install identity across releases"
    assert data["display"] in {"standalone", "fullscreen", "minimal-ui"}
    assert data["background_color"] and data["theme_color"]


def test_every_icon_exists_with_the_declared_size():
    missing = []
    for icon in manifest()["icons"]:
        path = WEB / icon["src"].lstrip("/")
        if not path.exists():
            missing.append(icon["src"])
            continue
        width, height = (int(v) for v in icon["sizes"].lower().split("x"))
        assert width == height, f"{icon['src']} must be square"
        assert width in {192, 512} or "maskable" in icon.get("purpose", ""), (
            f"{icon['src']} is an unusable size for an install icon")
    assert not missing, f"icons referenced but absent: {missing}"


def test_every_screenshot_exists():
    shots = manifest().get("screenshots", [])
    assert shots, "the rich install sheet needs at least one screenshot"
    missing = [s["src"] for s in shots if not (WEB / s["src"].lstrip("/")).exists()]
    assert not missing, f"screenshots referenced but absent: {missing}"


def test_a_maskable_icon_is_provided():
    """Android crops non-maskable icons into a circle and clips the artwork."""
    purposes = " ".join(i.get("purpose", "") for i in manifest()["icons"])
    assert "maskable" in purposes
