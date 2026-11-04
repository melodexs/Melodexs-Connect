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


def test_the_desktop_sidebar_menu_leaves_out_profile_but_the_chip_opens_it():
    """The account chip (photo, name, phone) already leads to Profile, so a
    separate Profile menu item on desktop is redundant. Phones have no chip and
    keep the Profile tab in the bottom bar."""
    menu = UI[UI.index('<nav class="sidebar-nav"'):UI.index('"</nav>"')]
    assert 'f.key !== "profile"' in menu, "Profile must be filtered out of the sidebar menu"
    chip = UI[UI.index('<a class="sidebar-user'):UI.index("sidebar-user-text")]
    assert 'href="/purchase-pin.html"' in chip, "the account chip must open Profile"
    assert 'activeFeature === "profile"' in chip, "the chip carries the highlight on the Profile page"
    assert '["home", "data", "wallet", "profile"]' in UI, "the phone bottom bar keeps Profile"


def test_the_account_chip_has_an_active_style():
    css = (WEB / "styles.css").read_text()
    assert ".sidebar-user.active" in css
