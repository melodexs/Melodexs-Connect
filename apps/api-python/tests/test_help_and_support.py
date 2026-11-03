"""Users must always be able to reach a human.

A pending purchase or a delayed funding is stressful; the support route is what
turns that into trust. These tests keep the page, its contact details and every
entry point to it from silently disappearing or drifting apart.
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
HELP = (WEB / "help.html").read_text()

# One source of truth for the number, in the three forms a page needs.
LOCAL = "0806 834 7514"
E164 = "+2348068347514"
WA = "https://wa.me/2348068347514"


def test_help_page_offers_whatsapp_call_and_email():
    assert WA in HELP, "WhatsApp is the fastest route and must stay"
    assert f'href="tel:{E164}"' in HELP
    assert "mailto:okohmelody30@gmail.com" in HELP


def test_the_contact_number_is_consistent_everywhere():
    """A number that differs between pages sends someone's complaint nowhere."""
    for name in ("help.html", "offline.html", "privacy.html"):
        text = (WEB / name).read_text()
        digits = set(re.findall(r"(?:wa\.me/|tel:\+)(\d{12,13})", text))
        assert digits <= {"2348068347514"}, f"{name} carries a different number: {digits}"
        assert digits, f"{name} should carry the support number"


def test_the_whatsapp_link_opens_safely():
    link = re.search(r'<a[^>]+href="https://wa\.me/[^"]+"[^>]*>', HELP).group(0)
    assert 'rel="noopener"' in link, "target=_blank without noopener exposes window.opener"


def test_faq_covers_the_questions_that_actually_cause_tickets():
    text = HELP.lower()
    for topic in ("pending", "failed", "funded my wallet", "wrong number", "purchase pin", "forgot my password"):
        assert topic in text, f"the FAQ should answer: {topic}"


def test_the_pending_advice_says_not_to_buy_again():
    """Double-buying is the costly mistake; the page must discourage it."""
    assert "don't buy it again" in HELP.lower() or "do not buy it again" in HELP.lower()


def test_help_never_asks_for_secrets():
    lowered = HELP.lower()
    assert "never share your password" in lowered
    assert "enter your pin" not in lowered and "send us your pin" not in lowered


def test_every_entry_point_links_to_help():
    entry_points = {
        "index.html": "landing footer",
        "purchase-pin.html": "profile page",
        "wallet.html": "pending-transaction note",
    }
    for name, where in entry_points.items():
        assert 'href="/help.html"' in (WEB / name).read_text() or "\\/help.html" in (WEB / name).read_text(), (
            f"{where} ({name}) should link to /help.html")


def test_the_offline_page_still_shows_a_phone_number():
    """No data is exactly when someone needs a number they can dial."""
    offline = (WEB / "offline.html").read_text()
    assert f'href="tel:{E164}"' in offline
    assert not re.search(r"<script[^>]+src=", offline), "offline page must stay self-contained"


def test_help_is_public_and_crawlable():
    robots = (WEB / "robots.txt").read_text()
    assert "Disallow: /help.html" not in robots
    assert "/help.html" in (WEB / "sitemap.xml").read_text()


def test_help_registers_the_service_worker_so_it_works_offline():
    assert "/pwa.js" in HELP
