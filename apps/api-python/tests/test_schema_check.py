import os
import subprocess
import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from app.schema_check import (
    EXPECTED_INDEX_DEFINITIONS,
    _compact_sql,
    _default_matches,
    _generated_id_missing,
    _index_issue,
    _type_ok,
)


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("users", "is_admin"),
        ("data_plans", "active"),
        ("data_plans", "provider_available"),
    ],
)
def test_postgres_flag_types_match_integer_runtime_queries(table, column):
    assert _type_ok(table, column, "integer")
    assert _type_ok(table, column, "smallint")
    assert not _type_ok(table, column, "boolean")


def test_postgres_partial_index_predicate_comparison_normalizes_formatting():
    assert _compact_sql('(source IS NOT NULL) AND (provider_code IS NOT NULL) AND (provider_package_code IS NOT NULL)') == "sourceisnotnullandprovider_codeisnotnullandprovider_package_codeisnotnull"


@pytest.mark.parametrize(
    ("actual", "allowed"),
    [
        ("0", {"0"}),
        ("((0)::double precision)", {"0"}),
        ("(1)::integer", {"1"}),
        ("('pending'::character varying)", {"'pending'::text", "'pending'"}),
        ("CURRENT_TIMESTAMP", {"current_timestamp", "now()"}),
        ("now()", {"current_timestamp", "now()"}),
    ],
)
def test_postgres_catalog_defaults_accept_harmless_formatting_and_casts(actual, allowed):
    assert _default_matches(actual, allowed)


def test_postgres_catalog_default_check_rejects_different_default_value():
    assert not _default_matches("(2)::double precision", {"0"})


def test_expected_index_definitions_preserve_key_order_and_partial_predicates():
    assert EXPECTED_INDEX_DEFINITIONS["uq_users_reset_token_hash"] == (
        True, ("reset_token_hash",), "reset_token_hashisnotnull"
    )
    assert EXPECTED_INDEX_DEFINITIONS["uq_data_plans_provider_package"] == (
        True,
        ("source", "provider_code", "provider_package_code"),
        "sourceisnotnullandprovider_codeisnotnullandprovider_package_codeisnotnull",
    )
    assert EXPECTED_INDEX_DEFINITIONS["uq_transactions_reference"] == (
        True, ("reference",), "referenceisnotnull"
    )
    assert EXPECTED_INDEX_DEFINITIONS["uq_transactions_user_idempotency"] == (
        True, ("user_id", "idempotency_key"), "idempotency_keyisnotnull"
    )


def test_index_check_rejects_wrong_order_uniqueness_validity_readiness_and_predicate():
    wanted = EXPECTED_INDEX_DEFINITIONS["uq_transactions_user_idempotency"]
    good = {
        "indisunique": True,
        "indisvalid": True,
        "indisready": True,
        "columns": ["user_id", "idempotency_key"],
        "predicate": "(idempotency_key IS NOT NULL)",
    }
    assert _index_issue(good, wanted) is None
    for field, value in (
        ("columns", ["idempotency_key", "user_id"]),
        ("indisunique", False),
        ("indisvalid", False),
        ("indisready", False),
        ("predicate", "idempotency_key IS NOT NULL AND status = 'pending'"),
    ):
        wrong = {**good, field: value}
        assert _index_issue(wrong, wanted) is not None


@pytest.mark.parametrize(
    ("default", "identity", "missing"),
    [
        ('nextval(\'users_id_seq\'::regclass)', "NO", False),
        (None, "YES", False),
        (None, "NO", True),
    ],
)
def test_generated_id_check_accepts_serial_and_identity_but_requires_generation(
    default, identity, missing
):
    assert _generated_id_missing(
        {"column_default": default, "is_identity": identity}
    ) is missing


def test_schema_incompatibilities_returns_only_violating_tables():
    from app.schema_check import schema_incompatibilities

    schema = {
        "users": {"missing": [], "missing_indexes": [], "incompatible_types": {}},
        "sessions": {"missing": ["sessions"], "missing_indexes": [], "incompatible_types": {}},
    }
    incompatible = schema_incompatibilities(schema)
    assert set(incompatible) == {"sessions"}
    assert incompatible["sessions"] == {"missing": ["sessions"]}


def test_schema_check_cli_exits_zero_and_reports_compatible_when_schema_is_current():
    import subprocess
    import sys

    from app.database import init_schema

    init_schema()
    result = subprocess.run(
        [sys.executable, "-m", "app.schema_check"],
        capture_output=True, text=True, cwd=_APP_DIR, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert '"compatible": true' in result.stdout
    assert result.stderr == ""


def test_schema_check_cli_exits_nonzero_with_non_sensitive_diagnostics_on_missing_schema():
    import subprocess
    import sys

    from app.database import db_session, init_schema, q

    init_schema()
    with db_session() as db:
        q(db, "DROP TABLE sessions")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.schema_check"],
            capture_output=True, text=True, cwd=_APP_DIR, check=False,
        )
        assert result.returncode == 1
        assert '"compatible": false' in result.stdout
        assert "sessions" in result.stderr
        # Diagnostics name columns/indexes/tables only; no row contents.
        assert "@" not in result.stderr and "hash" not in result.stderr.lower().replace("reset_token_hash", "")
    finally:
        init_schema()
