"""Security headers contract.

The API serves both JSON (/api/*) and the mounted web app (/), so every
response carries the full header set: CSP, X-Frame-Options, Referrer-Policy,
Permissions-Policy, Cross-Origin-Opener-Policy, nosniff, HSTS. COEP is
deliberately excluded - it would break the Google sign-in popup.
"""
import re

from fastapi.testclient import TestClient

from app import main
from app.main import WEB_CSP


def test_api_responses_carry_security_headers():
    with TestClient(main.app) as client:
        response = client.get("/api/status")
        h = response.headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "max-age=" in h["strict-transport-security"]
        assert h["permissions-policy"] == "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        assert h["cross-origin-opener-policy"] == "same-origin-allow-popups"
        assert h["content-security-policy"] == WEB_CSP


def test_blocked_responses_carry_security_headers():
    with TestClient(main.app) as client:
        response = client.get("/api/status", headers={"Origin": "https://evil.example"})
        assert response.status_code == 403
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["content-security-policy"] == WEB_CSP


def test_csp_allows_only_expected_origins():
    # script sources: self, inline, and Google Identity Services only
    script = re.search(r"script-src ([^;]+);", WEB_CSP).group(1)
    assert "accounts.google.com" in script
    assert "'self'" in script
    assert script.count("https://") == 1
    # no COEP anywhere: it breaks the Google sign-in popup
    assert "Cross-Origin-Embedder-Policy" not in WEB_CSP
    # frame-ancestors none complements X-Frame-Options DENY
    assert "frame-ancestors 'none'" in WEB_CSP
    # object-src and base-uri locked down
    assert "object-src 'none'" in WEB_CSP
    assert "base-uri 'self'" in WEB_CSP
