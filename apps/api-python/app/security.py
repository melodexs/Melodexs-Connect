import base64
import hashlib
import hmac
import json
import secrets
import time
from itsdangerous import BadSignature, URLSafeSerializer
import bcrypt
from fastapi import HTTPException, Request, Response
from .config import settings
from .database import db_session, q

COOKIE = "melodexs_session"
serializer = URLSafeSerializer(settings.session_secret, salt="melodexs-connect-session")


def password_hash(value: str) -> str:
    return bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()


def password_check(value: str, stored: str) -> bool:
    try:
        return bcrypt.checkpw(value.encode(), stored.encode())
    except (ValueError, TypeError):
        return False


def new_session(response: Response, user_id: int):
    sid = secrets.token_urlsafe(32)
    expires = int(time.time() * 1000) + 86400000
    with db_session() as db:
        q(db, "INSERT INTO sessions(sid, sess, expire) VALUES(:sid,:sess,:expire) ON CONFLICT(sid) DO UPDATE SET sess=:sess, expire=:expire", {"sid": sid, "sess": json.dumps({"userId": user_id}), "expire": expires})
    response.set_cookie(COOKIE, serializer.dumps(sid), max_age=86400, httponly=True, secure=settings.production, samesite="none" if settings.production else "lax")


def clear_session(request: Request, response: Response):
    sid = session_id(request)
    if sid:
        with db_session() as db:
            q(db, "DELETE FROM sessions WHERE sid=:sid", {"sid": sid})
    response.delete_cookie(COOKIE)
    # Also remove the old cookie name when switching from Express.
    response.delete_cookie("connect.sid")


def session_id(request: Request) -> str | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        return serializer.loads(raw)
    except BadSignature:
        return None


def current_user_id(request: Request) -> int | None:
    sid = session_id(request)
    if not sid:
        return None
    with db_session() as db:
        row = q(db, "SELECT sess, expire FROM sessions WHERE sid=:sid", {"sid": sid}).mappings().first()
        if not row or int(row["expire"]) <= int(time.time() * 1000):
            return None
        return int(json.loads(row["sess"])["userId"])


def require_user(request: Request) -> int:
    user_id = current_user_id(request)
    if not user_id:
        raise HTTPException(401, "Please log in to continue")
    return user_id


def require_admin(request: Request) -> int:
    user_id = require_user(request)
    with db_session() as db:
        row = q(db, "SELECT is_admin FROM users WHERE id=:id", {"id": user_id}).scalar()
    if not row:
        raise HTTPException(403, "Admin access required")
    return user_id


def valid_paystack_signature(secret: str | None, raw: bytes, received: str | None) -> bool:
    if not secret or not received:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, received)

