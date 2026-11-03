"""Google Sign-In verification and account provisioning.

The frontend renders the official Google Identity Services button, which
returns a signed ID token (JWT credential). This module verifies that
credential against Google's tokeninfo endpoint (Google performs the
signature and expiry check server-side), then enforces the token's
issuer, audience, and verified-email claims locally before any account
is created or authenticated.
"""
import time
import httpx
from fastapi import HTTPException
from .config import settings

TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
VALID_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


def verify_google_credential(credential: str) -> dict:
    """Verify a Google ID token and return its validated claims.

    Raises HTTPException(401) for any invalid, expired, tampered or
    mismatched credential so callers never trust an unverified token.
    """
    if not credential or not isinstance(credential, str) or len(credential) > 8192:
        raise HTTPException(401, "Invalid Google credential")
    if not settings.google_client_id:
        raise HTTPException(503, "Google sign-in is not configured")
    try:
        response = httpx.get(TOKENINFO_URL, params={"id_token": credential}, timeout=10.0)
    except httpx.HTTPError:
        raise HTTPException(502, "Could not reach Google to verify your sign-in. Please try again.")
    if response.status_code != 200:
        raise HTTPException(401, "Google sign-in could not be verified. Please try again.")
    claims = response.json()

    if str(claims.get("aud")) != str(settings.google_client_id):
        raise HTTPException(401, "Google credential was not issued for this app")
    if str(claims.get("iss")) not in VALID_ISSUERS:
        raise HTTPException(401, "Google credential has an unrecognised issuer")
    try:
        if int(claims.get("exp") or 0) <= int(time.time()):
            raise HTTPException(401, "Google credential has expired. Please try again.")
    except (TypeError, ValueError):
        raise HTTPException(401, "Google credential is malformed")
    email = str(claims.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(401, "Google credential has no verified email address")
    verified = claims.get("email_verified")
    if verified not in (True, "true", "True", 1, "1"):
        raise HTTPException(401, "Your Google account email is not verified")
    return {"email": email, "name": (str(claims.get("name") or "").strip() or email.split("@")[0])}
