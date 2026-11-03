import time
from .database import db_session, q
from .database import engine


LIMITS = {
    "/api/login": (10, 900),
    "/api/register": (10, 3600),
    "/api/auth/google": (10, 3600),
    "/api/forgot-password": (5, 900),
    "/api/reset-password": (10, 900),
    "/api/purchase-pin/set": (10, 900),
    "/api/purchase-pin/change": (10, 900),
    "/api/purchase-pin/verify": (20, 900),
    "/api/purchase-data": (20, 900),
    "/api/purchase-airtime": (20, 900),
    "/api/fund-wallet": (10, 900),
    "/api/fund-wallet/verify": (20, 900),
}


def init_rate_limit_table():
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS api_rate_limits (rate_key TEXT PRIMARY KEY, window_start BIGINT NOT NULL, request_count INTEGER NOT NULL)")


def allowed(path: str, key: str, db=None) -> tuple[bool, str]:
    """Check/consume a rate-limit slot.

    Pass an existing session as `db` to reuse the caller's single database
    connection instead of acquiring another one (each acquisition costs a
    full network round trip against the production serverless database).
    """
    limit, window = LIMITS.get(path, (0, 0))
    if not limit:
        return True, ""
    now = int(time.time())
    if db is None:
        with db_session() as own_db:
            return _consume(own_db, path, key, now, limit, window)
    return _consume(db, path, key, now, limit, window)


def _consume(db, path: str, key: str, now: int, limit: int, window: int) -> tuple[bool, str]:
        # One upsert serializes initialization, window rollover, and increment
        # on the rate_key in both supported dialects. A missing RETURNING row
        # means the existing, unexpired counter has already reached its limit.
        row = q(db, """
            INSERT INTO api_rate_limits(rate_key,window_start,request_count)
            VALUES(:key,:now,1)
            ON CONFLICT(rate_key) DO UPDATE SET
                window_start=CASE WHEN api_rate_limits.window_start <= :cutoff THEN :now ELSE api_rate_limits.window_start END,
                request_count=CASE WHEN api_rate_limits.window_start <= :cutoff THEN 1 ELSE api_rate_limits.request_count+1 END
            WHERE api_rate_limits.window_start <= :cutoff OR api_rate_limits.request_count < :limit
            RETURNING request_count
        """, {"key": key, "now": now, "cutoff": now - window, "limit": limit}).first()
        # Persist the counter immediately: a shared caller session may roll
        # back later (e.g. a rejected login), and a rolled-back increment
        # would silently disable the limit.
        db.commit()
        if row is None:
            return False, "Too many login attempts. Please try again later." if path == "/api/login" else "Too many requests. Please try again later."
        return True, ""

