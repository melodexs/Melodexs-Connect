"""Admin dashboard: the attention strip, navigation, search and honest wording.

admin.html is one static page with its own inline styles (it does not load
styles.css), so these pin its structure. The behaviour itself was exercised in a
real browser against sample data: search and every filter, XSS-style text,
empty data, one endpoint failing, a non-admin, and a 390px phone.
"""
import re
from pathlib import Path

import pytest

ADMIN = (Path(__file__).resolve().parents[3] / "apps" / "web" / "admin.html").read_text(encoding="utf-8")


def ids(html):
    return set(re.findall(r'\bid="([^"]+)"', html))


def test_every_nav_link_points_at_a_real_section():
    nav = ADMIN[ADMIN.index('id="adminNav"'):]
    nav = nav[:nav.index("</nav>")]
    targets = re.findall(r'href="#([^"]+)"', nav)
    assert len(targets) >= 6
    missing = [t for t in targets if t not in ids(ADMIN)]
    assert not missing, f"nav links with no matching section: {missing}"


def test_the_attention_strip_covers_the_things_an_owner_must_act_on():
    for card in ("attnPending", "attnFailed", "attnToday", "attnEmpty"):
        assert f'id="{card}"' in ADMIN
    assert 'id="navPending"' in ADMIN, "pending count badge in the nav"
    # Each card links to the section where the owner acts on it.
    assert 'href="#pendingPurchaseSection" id="attnPending"' in ADMIN


def test_users_and_transactions_are_searchable_and_filterable_with_labels():
    for control in ("userSearch", "userFilter", "txSearch", "txStatus", "txType"):
        assert f'id="{control}"' in ADMIN
        assert f'for="{control}"' in ADMIN, f"{control} needs a real label, not just a placeholder"
    for counter in ("userCount", "txCount"):
        assert f'id="{counter}"' in ADMIN


def test_data_is_escaped_in_every_new_renderer():
    start = ADMIN.index("function renderUsers")
    end = ADMIN.index("// Take over the two tables")
    block = ADMIN[start:end]
    # A bare field read such as ${user.name} or ${t.description} would put
    # customer-controlled text into the page unescaped.
    bare = re.findall(r"\$\{\s*(?:user|t)\.[A-Za-z_]+\s*\}", block)
    assert not bare, f"unescaped field in a renderer: {bare}"
    assert block.count("escapeHtml(") >= 12, "the row templates should escape their fields"


def test_one_failing_section_does_not_blank_the_others():
    assert "Promise.allSettled([" in ADMIN
    assert "Promise.all([" not in ADMIN, "Promise.all lets the first failure abort every other section"
    assert "Some sections could not load." in ADMIN


def test_admin_wording_no_longer_claims_a_single_supplier():
    # ISQUAREDATA is the primary provider; the page must not hard-code WiseSub as
    # "the" catalog or "the" route. (WiseSub still appears as a provider NAME in
    # data returned by the API, which is fine.)
    assert "Synchronize WiseSub plans" not in ADMIN
    assert "purchases continue through WiseSub" not in ADMIN
    assert "Synchronize catalog plans" in ADMIN


def test_admin_keeps_its_isolation_and_access_check():
    assert "styles.css" not in ADMIN, "admin ships its own inline styles; keep it isolated from customer CSS"
    assert "Number(user.is_admin) !== 1" in ADMIN, "non-admins must still be turned away client-side"
    assert 'content="noindex, nofollow"' in ADMIN


@pytest.mark.parametrize("needle", [
    "scroll-padding-top", "backdrop-filter", ":focus-visible",
])
def test_navigation_polish_is_present(needle):
    assert needle in ADMIN


def test_the_nav_is_keyboard_and_screen_reader_friendly():
    assert 'aria-label="Admin sections"' in ADMIN
    assert 'aria-live="polite"' in ADMIN, "counts and cards announce when they update"
    assert 'class="sr-only"' in ADMIN
