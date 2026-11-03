"""Every feature must be reachable, on every device.

The desktop sidebar and the mobile bottom bar are built from one list in ui.js.
Losing an entry means a paying feature becomes unreachable, which is exactly the
bug a four-tab navigation once caused.
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
UI = (WEB / "ui.js").read_text()

REQUIRED_FEATURES = {
    "home": "/dashboard.html",
    "data": "/buy-data.html",
    "airtime": "/buy-airtime.html",
    "electricity": "/buy-electricity.html",
    "cable": "/buy-cable.html",
    "education": "/buy-education.html",
    "wallet": "/wallet.html",
    "profile": "/purchase-pin.html",
}


def test_every_feature_is_declared_with_its_route():
    for key, href in REQUIRED_FEATURES.items():
        assert f'key: "{key}"' in UI, f"{key} missing from the feature list"
        assert f'href: "{href}"' in UI, f"{key} points somewhere unexpected"
        assert (WEB / href.lstrip("/")).exists(), f"{href} does not exist"


def test_every_feature_has_an_icon():
    """An entry without an icon renders as an empty gap in the sidebar."""
    icons = len(re.findall(r'key: "\w+", href: "[^"]+", label: "[^"]+", icon:', UI))
    assert icons == len(REQUIRED_FEATURES), f"expected {len(REQUIRED_FEATURES)} icons, found {icons}"


def test_each_page_maps_to_its_own_entry():
    for key, href in REQUIRED_FEATURES.items():
        assert f'"{href}": "{key}"' in UI, f"{href} is not mapped to the {key} entry"


def test_the_mobile_bar_keeps_the_four_primary_destinations():
    assert '["home", "data", "wallet", "profile"]' in UI
