"""The admin dashboard must offer a way back to the main app without signing out."""
from pathlib import Path

ADMIN = (Path(__file__).resolve().parents[3] / "apps" / "web" / "admin.html").read_text(encoding="utf-8")
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def test_admin_header_links_back_to_the_app():
    head = ADMIN[ADMIN.index("<header>"):ADMIN.index("</header>")]
    assert 'href="/dashboard.html"' in head
    assert "Back to app" in head


def test_back_target_exists_and_logout_is_kept():
    assert (WEB / "dashboard.html").exists()
    head = ADMIN[ADMIN.index("<header>"):ADMIN.index("</header>")]
    assert 'onclick="logout()"' in head
