import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///" + str(Path(__file__).parent / "test.db"))
os.environ.setdefault("NODE_ENV", "test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-python-api")

from app.database import init_schema
from app.rate_limit import init_rate_limit_table


def pytest_sessionstart(session):
    init_schema()
    init_rate_limit_table()
import pytest
from app.database import db_session, q
@pytest.fixture(autouse=True)
def reset_rate_limits():
    with db_session() as db:
        q(db, "DELETE FROM api_rate_limits")
