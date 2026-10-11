import pytest

from app.schema_check import _type_ok


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
