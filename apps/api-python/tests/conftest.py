import os
import sys
import asyncio
from pathlib import Path
from urllib.parse import urlparse

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# Default tests are isolated SQLite. PostgreSQL integration is an explicit
# opt-in and accepts only a database name that identifies a test/stage DB.
PG_INTEGRATION = os.environ.get("RUN_POSTGRES_INTEGRATION") == "1"
if PG_INTEGRATION:
    target = os.environ.get("TEST_POSTGRES_URL", "")
    parsed = urlparse(target)
    db_name = parsed.path.lstrip("/").lower()
    if not parsed.scheme.startswith("postgres") or not db_name or not any(token in db_name for token in ("test", "stage")) or "prod" in db_name:
        raise RuntimeError("PostgreSQL integration requires TEST_POSTGRES_URL to name a dedicated test/stage database")
    os.environ["DATABASE_URL"] = target
    os.environ["NODE_ENV"] = "production"  # select read-only app startup
    os.environ["SESSION_SECRET"] = "postgres-integration-test-session-secret"
else:
    os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(__file__).parent / "test_suite.db")
    os.environ["NODE_ENV"] = "test"
    os.environ["SESSION_SECRET"] = "test-session-secret-for-python-api"

from app.database import init_schema
from app.rate_limit import init_rate_limit_table

# This sandbox cannot run AnyIO's worker pool (a minimal FastAPI TestClient
# request stalls even for a one-route app). Use HTTPX's in-process ASGI
# transport and execute sync test handlers inline. Production routing remains
# unchanged; database calls in this test adapter still exercise the real code.
import fastapi.routing
import fastapi.testclient
import httpx
import anyio.to_thread


async def _inline_sync_handler(func, *args, **kwargs):
    return func(*args, **kwargs)


fastapi.routing.run_in_threadpool = _inline_sync_handler


async def _inline_file_operation(func, *args, **kwargs):
    kwargs.pop("abandon_on_cancel", None)
    kwargs.pop("cancellable", None)
    kwargs.pop("limiter", None)
    return func(*args, **kwargs)


anyio.to_thread.run_sync = _inline_file_operation


class ASGITestClient:
    __test__ = False

    def __init__(self, app, **kwargs):
        self.app = app
        self.cookies = httpx.Cookies()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def request(self, method, url, **kwargs):
        async def send():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://testserver",
                cookies=self.cookies,
            ) as client:
                response = await client.request(method, url, **kwargs)
                self.cookies.update(client.cookies)
                return response

        return asyncio.run(send())

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def patch(self, url, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def options(self, url, **kwargs):
        return self.request("OPTIONS", url, **kwargs)


fastapi.testclient.TestClient = ASGITestClient


def pytest_sessionstart(session):
    if not PG_INTEGRATION:
        init_schema()
        init_rate_limit_table()
    from app.main import startup
    startup()
import pytest
from app.database import db_session, q
@pytest.fixture(autouse=True)
def reset_rate_limits():
    with db_session() as db:
        q(db, "DELETE FROM api_rate_limits")
