"""The site moves to melodex.com.ng without breaking the old address.

* On melodex.com.ng the page must call api.melodex.com.ng (one registrable
  domain, so the session cookie is first-party everywhere, including Safari).
* On the old onrender.com address, saved links and installed apps must keep
  using the old API exactly as before.
* An explicit <meta name="api-base-url"> (staging) and local development keep
  winning over both.
* The Content-Security-Policy must list BOTH API addresses, or the browser
  blocks every call to the one that is missing.

api.js is browser code, so these tests actually execute it in Node with a fake
`window`/`document` for each hostname, rather than just reading its text.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.main import WEB_CSP

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web"

OLD_API = "https://melodexs-connect-api.onrender.com"
NEW_API = "https://api.melodex.com.ng"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is required to execute api.js")

_HARNESS = r"""
const fs = require("fs");
const hostname = process.argv[1];
const metaValue = process.argv[2] === "-" ? "" : process.argv[2];
let seen = null;
global.window = { location: { hostname, origin: "https://" + hostname },
                  fetch: (url) => { seen = String(url); return Promise.resolve({}); } };
global.document = { querySelector: () => (metaValue ? { content: metaValue } : null) };
global.localStorage = { getItem: () => null };
global.Headers = class { constructor(){ this.m = {}; } has(){ return false; } set(){} };
eval(fs.readFileSync(process.env.API_JS, "utf8"));
window.fetch("/api/status").then(() => console.log(JSON.stringify({ url: seen })));
"""


def _url_called_from(hostname, meta=""):
    out = subprocess.run(
        ["node", "-e", _HARNESS, hostname, meta or "-"],
        capture_output=True, text=True, timeout=30,
        env={"API_JS": str(WEB / "api.js"), "PATH": "/usr/bin:/usr/local/bin:/bin"},
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])["url"]


@pytest.mark.parametrize("host", ["melodex.com.ng", "www.melodex.com.ng"])
def test_custom_domain_calls_the_new_api(host):
    assert _url_called_from(host) == NEW_API + "/api/status"


def test_old_address_keeps_using_the_old_api():
    assert _url_called_from("melodexs-connect.onrender.com") == OLD_API + "/api/status"


def test_staging_meta_override_still_wins():
    staging = "https://staging-api.example.test"
    assert _url_called_from("melodex.com.ng", staging) == staging + "/api/status"


def test_local_development_still_uses_the_page_origin():
    assert _url_called_from("localhost") == "https://localhost/api/status"


def test_lookalike_hosts_do_not_get_the_new_api():
    for host in ("melodex.com.ng.evil.example", "evil-melodex.com.ng", "api.melodex.com.ng"):
        assert _url_called_from(host) == OLD_API + "/api/status", host


def test_content_security_policy_allows_both_apis():
    connect = re.search(r"connect-src ([^;]+);", WEB_CSP).group(1).split()
    assert OLD_API in connect and NEW_API in connect
    assert "*" not in connect, "connect-src must stay an explicit allow-list"


def test_public_files_describe_the_new_domain():
    for name in ("sitemap.xml", "robots.txt", "index.html", ".well-known/security.txt"):
        text = (WEB / name).read_text(encoding="utf-8")
        assert "https://melodex.com.ng" in text, name
        assert "melodexs-connect.onrender.com" not in text, f"{name} still names the old address"


def test_single_production_constant_is_preserved():
    api_js = (WEB / "api.js").read_text(encoding="utf-8")
    assert api_js.count("const PRODUCTION_API_URL") == 1
    assert api_js.count("const CUSTOM_DOMAIN_API_URL") == 1
