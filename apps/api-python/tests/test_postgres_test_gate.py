import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from postgres_test_gate import (
    postgres_integration_enabled,
    validate_postgres_test_target,
    verify_connected_postgres_identity,
)


def _env(url="postgresql+psycopg://tester:secret@pg.example.invalid/island?sslmode=verify-full"):
    return {
        "POSTGRES_TEST_DATABASE_VERIFIED": "YES",
        "POSTGRES_TEST_DATABASE_URL": url,
        "POSTGRES_TEST_EXPECTED_HOST": "pg.example.invalid",
        "POSTGRES_TEST_EXPECTED_DATABASE": "island",
        "POSTGRES_TEST_EXPECTED_USERNAME": "tester",
    }


def test_postgres_integration_is_disabled_by_default_and_ignores_other_values():
    assert not postgres_integration_enabled({})
    assert not postgres_integration_enabled({"POSTGRES_TEST_DATABASE_URL": "not-a-url"})
    assert postgres_integration_enabled({"RUN_POSTGRES_INTEGRATION": "1"})


def test_invalid_opt_in_fails_before_database_engine_import_or_creation():
    repo_root = Path(__file__).resolve().parents[3]
    conftest = Path(__file__).resolve().parent / "conftest.py"
    child = """
import runpy, sqlalchemy, sys
created = []
sqlalchemy.create_engine = lambda *args, **kwargs: created.append((args, kwargs))
try:
    runpy.run_path(sys.argv[1])
except RuntimeError:
    pass
else:
    raise SystemExit(2)
assert not created
assert 'app.database' not in sys.modules
"""
    env = os.environ.copy()
    for name in (
        "POSTGRES_TEST_DATABASE_VERIFIED",
        "POSTGRES_TEST_DATABASE_URL",
        "POSTGRES_TEST_EXPECTED_HOST",
        "POSTGRES_TEST_EXPECTED_DATABASE",
        "POSTGRES_TEST_EXPECTED_USERNAME",
    ):
        env.pop(name, None)
    env["RUN_POSTGRES_INTEGRATION"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", child, str(conftest)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


@pytest.mark.parametrize(
    "updates, message",
    [
        ({"POSTGRES_TEST_DATABASE_VERIFIED": ""}, "POSTGRES_TEST_DATABASE_VERIFIED"),
        ({"POSTGRES_TEST_DATABASE_URL": ""}, "POSTGRES_TEST_DATABASE_URL"),
        ({"POSTGRES_TEST_DATABASE_URL": "["}, "POSTGRES_TEST_DATABASE_URL"),
        ({"POSTGRES_TEST_EXPECTED_HOST": ""}, "POSTGRES_TEST_EXPECTED_HOST"),
        ({"POSTGRES_TEST_EXPECTED_DATABASE": ""}, "POSTGRES_TEST_EXPECTED_DATABASE"),
        ({"POSTGRES_TEST_EXPECTED_USERNAME": ""}, "POSTGRES_TEST_EXPECTED_USERNAME"),
        ({"POSTGRES_TEST_EXPECTED_HOST": "other.example.invalid"}, "hostname"),
        ({"POSTGRES_TEST_EXPECTED_DATABASE": "other"}, "database"),
        ({"POSTGRES_TEST_EXPECTED_USERNAME": "other"}, "username"),
        ({"POSTGRES_TEST_DATABASE_URL": "postgresql://tester:secret@pg.example.invalid/island"}, "sslmode=verify-full"),
        ({"POSTGRES_TEST_DATABASE_URL": "postgresql://tester:secret@pg.example.invalid/island?sslmode=verify-full&host=other.invalid"}, "ambiguous connection-target override"),
    ],
)
def test_invalid_postgres_target_configuration_fails_closed(updates, message):
    env = _env()
    env.update(updates)
    with pytest.raises(RuntimeError, match=message):
        validate_postgres_test_target(env)


def test_target_with_test_or_stage_name_is_not_safe_without_exact_allowlist():
    env = _env("postgresql://tester:secret@pg.example.invalid/stage_test?sslmode=verify-full")
    env.pop("POSTGRES_TEST_EXPECTED_DATABASE")
    with pytest.raises(RuntimeError, match="POSTGRES_TEST_EXPECTED_DATABASE"):
        validate_postgres_test_target(env)


def test_production_host_and_database_match_is_rejected_without_echoing_url():
    env = _env()
    production_url = "postgresql://prod-user:do-not-print@PG.EXAMPLE.INVALID/island"
    with pytest.raises(RuntimeError) as error:
        validate_postgres_test_target(env, [("DATABASE_URL", production_url)])
    assert "matches a configured application database" in str(error.value)
    assert production_url not in str(error.value)
    assert "do-not-print" not in str(error.value)


def test_application_database_url_must_not_be_malformed_or_ambiguous():
    with pytest.raises(RuntimeError, match="malformed"):
        validate_postgres_test_target(_env(), [("DATABASE_URL", "[")])
    with pytest.raises(RuntimeError, match="ambiguous"):
        validate_postgres_test_target(_env(), [("DATABASE_URL", "postgresql://app-user@db.example.invalid")])


def test_connected_identity_checks_database_user_and_configured_host():
    target = validate_postgres_test_target(_env())

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def exec_driver_sql(self, _statement):
            return SimpleNamespace(one=lambda: ("island", "tester", "192.0.2.8"))

    engine = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        url=SimpleNamespace(host="pg.example.invalid", database="island", username="tester"),
        connect=lambda: Connection(),
    )
    verify_connected_postgres_identity(engine, target)

    engine.url = SimpleNamespace(host="pg.example.invalid", database="wrong", username="tester")
    with pytest.raises(RuntimeError, match="engine target"):
        verify_connected_postgres_identity(engine, target)


def test_connected_server_identity_mismatch_fails_without_driver_details():
    target = validate_postgres_test_target(_env())

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def exec_driver_sql(self, _statement):
            return SimpleNamespace(one=lambda: ("wrong-db", "wrong-user", "192.0.2.8"))

    engine = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        url=SimpleNamespace(host="pg.example.invalid", database="island", username="tester"),
        connect=lambda: Connection(),
    )
    with pytest.raises(RuntimeError, match="Connected PostgreSQL database identity"):
        verify_connected_postgres_identity(engine, target)


def test_connection_failure_is_sanitized():
    target = validate_postgres_test_target(_env())

    class Engine:
        dialect = SimpleNamespace(name="postgresql")
        url = SimpleNamespace(host="pg.example.invalid", database="island", username="tester")

        def connect(self):
            raise RuntimeError("postgresql://user:secret@production.invalid/prod")

    with pytest.raises(RuntimeError) as error:
        verify_connected_postgres_identity(Engine(), target)
    assert "secret" not in str(error.value)
    assert "production.invalid" not in str(error.value)
