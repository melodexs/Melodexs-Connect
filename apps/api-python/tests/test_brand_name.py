"""The product is called MELODEX. Pin the brand customers see, and pin the
identifiers that must NOT change.

Why the second half matters: the old name lives on in places customers never
read but production depends on. Renaming them in a well-meant clean-up would
sign everyone out (session cookie), break existing Android installs (package
id), point people at addresses that do not exist (Render hostnames) or lose the
saved theme. Those are listed here so the next person finds out why, from a
failing test, instead of from a support call.
"""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web"
API = REPO / "apps" / "api-python" / "app"

# Live addresses, code names and install identity. These legitimately keep the
# old spelling and are removed before looking for leftover brand text.
PROTECTED = re.compile("|".join([
    r"https?://melodexs-connect[a-z0-9.\-]*\.onrender\.com[^\s\"'<>)`]*",
    r"melodexs-connect[a-z0-9\-]*\.onrender\.com",
    r"melodexs/Melodexs-Connect",
    r"/?icons/melodexs-connect-\d+\.png",
    r"com\.melodexs\.connect",
    r"MELODEXS_[A-Z_]+",
    r"melodexs_session[.\w]*",
    r"melodexsTheme",
    r"melodexs_pwa_install_dismissed",
    r"melodexs-(?:static|pages|statement)[\w.\-]*",
    r"melodexs-install-[a-z]+",          # CSS class names in pwa.js
    r"melodexs-connect-session",         # salt that signs the session cookie: changing it signs everyone out
    r"melodexs-connect-maskable\.png",   # install icon file name
]))


def visible_files():
    for path in WEB.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".js", ".webmanifest", ".txt", ".xml"}:
            yield path
    for name in ("main.py", "config.py", "security.py"):
        yield API / name


def test_no_customer_facing_file_still_uses_the_old_brand():
    offenders = []
    for path in visible_files():
        text = PROTECTED.sub("", path.read_text(encoding="utf-8", errors="ignore"))
        for match in re.finditer(r"melodexs", text, re.IGNORECASE):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(REPO)}:{line}")
    assert not offenders, "old brand text found (use MELODEX): " + ", ".join(offenders[:12])


def test_the_word_connect_is_not_part_of_the_brand_any_more():
    offenders = []
    for path in visible_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        # also catches the URL-encoded form used in WhatsApp and mailto links
        for match in re.finditer(r"MELODEXS?(?:\s|%20|\+)*(?:<[^>]+>\s*)?CONNECT\b", text, re.IGNORECASE):
            offenders.append(f"{path.relative_to(REPO)}:{text.count(chr(10), 0, match.start()) + 1}")
    assert not offenders, "'MELODEX CONNECT' still present: " + ", ".join(offenders[:12])


def test_the_installed_app_and_pages_use_the_new_name():
    manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "MELODEX" and manifest["short_name"] == "MELODEX"
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert "<title>MELODEX |" in index
    assert 'content="MELODEX"' in index  # apple-mobile-web-app-title
    for page in ("login.html", "register.html", "dashboard.html", "wallet.html", "fund-wallet.html", "help.html"):
        text = (WEB / page).read_text(encoding="utf-8")
        assert re.search(r"<title>[^<]*MELODEX[^<]*</title>", text), page
    assert 'app_name">MELODEX<' in (REPO / "android/app/src/main/res/values/strings.xml").read_text(encoding="utf-8")


def test_the_server_identifies_itself_and_emails_as_melodex():
    main_py = (API / "main.py").read_text(encoding="utf-8")
    assert 'FastAPI(title="MELODEX API"' in main_py
    assert "MELODEX Password Reset" in main_py
    assert 'brevo_from_name: str = "MELODEX"' in (API / "config.py").read_text(encoding="utf-8")


# ---- identifiers that must keep the old spelling ---------------------------

def test_the_session_cookie_name_is_unchanged_so_nobody_is_signed_out():
    security = (API / "security.py").read_text(encoding="utf-8")
    assert 'COOKIE = "melodexs_session"' in security
    assert 'salt="melodexs-connect-session"' in security, "changing the salt invalidates every existing login"


def test_the_android_package_id_is_unchanged_so_installs_keep_updating():
    gradle = (REPO / "android/app/build.gradle").read_text(encoding="utf-8")
    assert 'applicationId "com.melodexs.connect"' in gradle
    assert 'namespace "com.melodexs.connect"' in gradle


def test_live_addresses_still_point_at_real_hosts():
    api_js = (WEB / "api.js").read_text(encoding="utf-8")
    assert "melodexs-connect-api.onrender.com" in api_js
    sitemap = (WEB / "sitemap.xml").read_text(encoding="utf-8")
    assert "melodex.com.ng" in sitemap


def test_internal_javascript_api_names_are_unchanged():
    ui = (WEB / "ui.js").read_text(encoding="utf-8")
    assert "window.MELODEXS_UI" in ui
    assert "MELODEXS_CATEGORIZED_CATALOG" in (WEB / "api.js").read_text(encoding="utf-8")


def test_install_icon_file_names_still_exist():
    manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
    for icon in manifest["icons"]:
        assert (WEB / icon["src"].lstrip("/")).is_file(), icon["src"]


def test_support_links_say_melodex_in_the_message_and_subject():
    help_page = (WEB / "help.html").read_text(encoding="utf-8")
    assert "text=Hello%20MELODEX%2C" in help_page
    assert "subject=MELODEX%20support" in help_page


def test_the_offline_cache_was_bumped_so_returning_visitors_get_the_new_name():
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    versions = [int(v) for v in re.findall(r'"melodexs-(?:static|pages)-v(\d+)"', sw)]
    assert versions and min(versions) >= 4, "v3 caches still hold pages that say the old name"
