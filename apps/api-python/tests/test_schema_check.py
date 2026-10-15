import pytest

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
