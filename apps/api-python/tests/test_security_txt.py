"""security.txt tells a researcher where to report a vulnerability.

An expired or contact-less file is worse than none: it says the project does not
answer. RFC 9116 requires Contact and recommends Expires.
"""
import re
from datetime import date
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
FILE = WEB / ".well-known" / "security.txt"


def test_the_file_is_published_where_crawlers_look():
    assert FILE.exists(), "expected apps/web/.well-known/security.txt"


def test_it_has_a_contact():
    text = FILE.read_text()
    contacts = [l for l in text.splitlines() if l.lower().startswith("contact:")]
    assert contacts, "RFC 9116 requires a Contact line"
    assert any("@" in c or "https://" in c for c in contacts)


def test_it_has_not_expired():
    text = FILE.read_text()
    match = re.search(r"^Expires:\s*(\S+)", text, re.M | re.I)
    assert match, "an Expires date tells researchers whether the file is current"
    expires = date.fromisoformat(match.group(1).strip()[:10])
    assert expires > date.today(), f"security.txt expired on {expires}"


def test_it_points_at_the_hardening_notes():
    text = FILE.read_text().lower()
    assert "policy" in text or "security.md" in text
