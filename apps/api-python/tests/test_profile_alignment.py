"""The Profile page's welcome block must line up with the text inside its cards.

The hero used to have no styles, so "Hello, Melody!" sat at the very edge of the
content while "Account Profile" sat a card padding further in. The numbers below
come from measuring the live page: 20px card padding + 1px card border.
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
CSS = (WEB / "styles.css").read_text()
PAGE = (WEB / "purchase-pin.html").read_text()


def rule(selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert match, f"missing CSS rule: {selector}"
    return match.group(1)


def test_the_profile_page_still_uses_the_screen_wrapper_and_hero():
    assert '<main class="screen">' in PAGE
    assert 'class="hero hero-compact"' in PAGE


def test_the_welcome_block_is_inset_by_exactly_the_card_text_offset():
    card = rule(".card")
    card_padding = int(re.search(r"padding:\s*(\d+)px", card).group(1))
    card_border = int(re.search(r"border:\s*(\d+)px", card).group(1))
    hero = rule("body.app-body main.screen > .hero")
    left = int(re.search(r"padding:\s*\d+px\s+(\d+)px", hero).group(1))
    assert left == card_padding + card_border, (
        f"hero inset {left}px must equal card padding {card_padding}px + border {card_border}px"
    )


def test_the_profile_page_has_a_side_gutter_so_cards_do_not_touch_the_screen_edge():
    screen = rule("body.app-body main.screen")
    assert re.search(r"padding:\s*\d+px\s+(\d+)px", screen), "main.screen needs horizontal padding"
    assert int(re.search(r"padding:\s*\d+px\s+(\d+)px", screen).group(1)) >= 12


def test_the_hero_lines_have_no_extra_side_margins_that_would_break_alignment():
    for selector in ("body.app-body main.screen > .hero .hero-hello",
                     "body.app-body main.screen > .hero .hero-title",
                     "body.app-body main.screen > .hero .hero-sub"):
        body = rule(selector)
        assert not re.search(r"margin(-left)?:\s*[^;]*\b[1-9]\d*px\s+[1-9]", body.split("margin:")[-1] if "margin:" in body else ""), selector
        assert "padding-left" not in body, selector
