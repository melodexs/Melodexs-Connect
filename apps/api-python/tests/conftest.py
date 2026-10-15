import os
import sys
import asyncio
from pathlib import Path
from dotenv import dotenv_values

API_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = API_ROOT.parents[1]
TEST_ROOT = Path(__file__).resolve().parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from postgres_test_gate import (
    postgres_integration_enabled,
    validate_postgres_test_target,
    verify_connected_postgres_identity,
)

# Default tests are isolated SQLite and ignore all PostgreSQL test variables.
PG_INTEGRATION = postgres_integration_enabled(os.environ)
POSTGRES_TEST_TARGET = None
if PG_INTEGRATION:
    file_values = dotenv_values(REPOSITORY_ROOT / ".env")
    configured_application_urls = [
        ("DATABASE_URL environment", os.environ.get("DATABASE_URL")),
        ("DATABASE_URL in repository .env", file_values.get("DATABASE_URL")),
    ]
    POSTGRES_TEST_TARGET = validate_postgres_test_target(os.environ, configured_application_urls)
    os.environ["DATABASE_URL"] = POSTGRES_TEST_TARGET.url.render_as_string(hide_password=False)
    os.environ["NODE_ENV"] = "production"  # select read-only app startup
    os.environ["WISESUB_ENVIRONMENT"] = "live"
    os.environ["WISESUB_BASE_URL"] = "https://app.wisesub.com.ng/api/partner/v1"
    os.environ["SESSION_SECRET"] = "postgres-integration-test-session-secret"
else:
    local_test_database = os.environ.get("PYTHON_TEST_DATABASE_URL")
    if local_test_database and (not local_test_database.startswith("sqlite:") or ":memory:" in local_test_database):
        raise RuntimeError("PYTHON_TEST_DATABASE_URL must point to a local SQLite test database")
    os.environ["DATABASE_URL"] = local_test_database or ("sqlite:///" + str(Path(__file__).parent / "test_suite.db"))
    os.environ["NODE_ENV"] = "test"
    os.environ["WISESUB_ENVIRONMENT"] = "test"
    os.environ["WISESUB_BASE_URL"] = "https://wisesub.test/api/partner/v1"
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
    else:
        from app.database import engine
        verify_connected_postgres_identity(engine, POSTGRES_TEST_TARGET)
    from app.main import startup
    startup()
import pytest
from app.database import db_session, q
@pytest.fixture(autouse=True)
def reset_rate_limits():
    with db_session() as db:
        q(db, "DELETE FROM api_rate_limits")
