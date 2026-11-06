"""Google Search Console ownership proof for melodex.com.ng.

The tag is public by design (it must be readable in the page source), but it
has to stay on the landing page or Google drops the verified property.
"""

import re
from pathlib import Path

INDEX = Path(__file__).resolve().parents[3] / "apps" / "web" / "index.html"


def test_landing_page_carries_exactly_one_google_verification_tag():
    html = INDEX.read_text(encoding="utf-8")
    tags = re.findall(r'<meta name="google-site-verification" content="([^"]+)">', html)
    assert len(tags) == 1
    assert re.fullmatch(r"[A-Za-z0-9_\-]{30,60}", tags[0])


def test_verification_tag_is_inside_the_head():
    html = INDEX.read_text(encoding="utf-8")
    head = html.split("</head>", 1)[0]
    assert "google-site-verification" in head
