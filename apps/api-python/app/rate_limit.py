import time
from .database import db_session, q
from .database import engine


LIMITS = {
    "/api/login": (10, 900),
    "/api/register": (10, 3600),
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


def allowed(path: str, key: str) -> tuple[bool, str]:
    limit, window = LIMITS.get(path, (0, 0))
    if not limit:
        return True, ""
    now = int(time.time())
    with db_session() as db:
        row = q(db, "SELECT window_start,request_count FROM api_rate_limits WHERE rate_key=:key", {"key": key}).mappings().first()
        if not row or now - int(row["window_start"]) >= window:
            q(db, "INSERT INTO api_rate_limits(rate_key,window_start,request_count) VALUES(:key,:start,1) ON CONFLICT(rate_key) DO UPDATE SET window_start=:start,request_count=1", {"key": key, "start": now})
            return True, ""
        if int(row["request_count"]) >= limit:
            return False, "Too many login attempts. Please try again later." if path == "/api/login" else "Too many requests. Please try again later."
        q(db, "UPDATE api_rate_limits SET request_count=request_count+1 WHERE rate_key=:key", {"key": key})
    return True, ""

