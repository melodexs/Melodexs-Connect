"""Read-only compatibility check for the Node API's PostgreSQL schema."""

from .database import engine

EXPECTED_COLUMNS = {
    "users": {"id", "name", "email", "phone", "password", "purchase_pin", "balance", "virtual_account_number", "virtual_bank_name", "kyc_status", "is_admin", "reset_token_hash", "reset_token_expires_at", "created_at"},
    "data_plans": {"id", "plan_name", "network", "plan", "provider_cost", "selling_price", "selling_price_override", "active", "provider_available", "category", "provider_category", "sync_error", "provider", "provider_code", "provider_package_code", "provider_package_name", "data_size", "validity", "source", "status", "last_synced_at", "created_at", "updated_at"},
    "data_plan_sync_runs": {"id", "started_at", "finished_at", "outcome", "added", "updated", "unavailable", "errors"},
    "transactions": {"id", "user_id", "type", "amount", "status", "reference", "description", "idempotency_key", "provider_reference", "created_at"},
    "sessions": {"sid", "sess", "expire"},
    "api_rate_limits": {"rate_key", "window_start", "request_count"},
}

# Types accepted by both the Node migration DDL and the existing Python SQL.
EXPECTED_TYPES = {
    "id": {"integer", "smallint", "bigint"},
    "user_id": {"integer", "smallint", "bigint"},
    "balance": {"double precision", "real", "numeric"},
    "amount": {"double precision", "real", "numeric"},
    "provider_cost": {"double precision", "real", "numeric"},
    "selling_price": {"double precision", "real", "numeric"},
    "selling_price_override": {"double precision", "real", "numeric"},
    # The Node PostgreSQL migration and runtime use integer flags and compare
    # them to 0/1. PostgreSQL BOOLEAN is not interchangeable in those queries.
    "is_admin": {"integer", "smallint"},
    "provider_available": {"integer", "smallint"},
    "active": {"integer", "smallint"},
    "expire": {"bigint", "integer"},
    "reset_token_expires_at": {"bigint", "integer"},
    "window_start": {"bigint", "integer"},
    "request_count": {"integer", "smallint", "bigint"},
    "added": {"integer", "smallint", "bigint"},
    "updated": {"integer", "smallint", "bigint"},
    "unavailable": {"integer", "smallint", "bigint"},
    "created_at": {"timestamp without time zone", "timestamp with time zone", "text", "character varying"},
    "updated_at": {"timestamp without time zone", "timestamp with time zone", "text", "character varying"},
    "last_synced_at": {"timestamp without time zone", "timestamp with time zone", "text", "character varying"},
    "started_at": {"timestamp without time zone", "timestamp with time zone", "text", "character varying"},
    "finished_at": {"timestamp without time zone", "timestamp with time zone", "text", "character varying"},
}
TEXT_COLUMNS = {
    "name", "email", "phone", "password", "purchase_pin", "virtual_account_number",
    "virtual_bank_name", "kyc_status", "reset_token_hash", "network", "plan_name",
    "plan", "provider", "provider_code", "provider_package_code", "provider_package_name",
    "data_size", "validity", "source", "status", "type", "reference", "description",
    "sid", "sess", "rate_key", "category", "provider_category", "sync_error", "idempotency_key", "provider_reference", "outcome", "errors",
}
EXPECTED_CONSTRAINTS = {
    "users": {"PRIMARY KEY(id)", "UNIQUE(email)", "UNIQUE(phone)"},
    "data_plans": {"PRIMARY KEY(id)", "UNIQUE(network,plan)"},
    "data_plan_sync_runs": {"PRIMARY KEY(id)"},
    "transactions": {"PRIMARY KEY(id)", "FOREIGN KEY(user_id)->users(id)"},
    "sessions": {"PRIMARY KEY(sid)"},
    "api_rate_limits": {"PRIMARY KEY(rate_key)"},
}
GENERATED_ID_COLUMNS = {"users": "id", "data_plans": "id", "data_plan_sync_runs": "id", "transactions": "id"}
EXPECTED_NOT_NULL = {
    "users": {"id", "name", "email", "phone", "password", "balance", "kyc_status", "is_admin", "created_at"},
    "data_plans": {"id", "network", "plan", "provider_cost", "selling_price", "active", "provider_available", "created_at", "updated_at"},
    "data_plan_sync_runs": {"id", "started_at", "outcome", "added", "updated", "unavailable"},
    "transactions": {"id", "user_id", "type", "amount", "status", "created_at"},
    "sessions": {"sid", "sess", "expire"},
    "api_rate_limits": {"rate_key", "window_start", "request_count"},
}
EXPECTED_INDEXES = {"sessions": {"idx_sessions_expire"}, "data_plans": {"uq_data_plans_provider_package"}, "transactions": {"uq_transactions_reference", "uq_transactions_user_idempotency"}}
EXPECTED_INDEX_PARTS = {
    "idx_sessions_expire": ("create index", "sessions", "expire"),
    "uq_data_plans_provider_package": ("create unique index", "data_plans", "source", "provider_code", "provider_package_code", "where", "is not null"),
    "uq_transactions_user_idempotency": ("create unique index", "transactions", "user_id", "idempotency_key", "where", "is not null"),
    "uq_transactions_reference": ("create unique index", "transactions", "reference", "where", "is not null"),
}


def _type_ok(table: str, column: str, data_type: str) -> bool:
    accepted = EXPECTED_TYPES.get(column)
    if accepted:
        return data_type in accepted
    if column in TEXT_COLUMNS:
        return data_type in {"text", "character varying", "character"}
    return True


def _postgres_schema(conn) -> dict:
    result = {}
    for table, expected in EXPECTED_COLUMNS.items():
        rows = conn.exec_driver_sql(
            "SELECT column_name,data_type,column_default,is_nullable,is_identity "
            "FROM information_schema.columns WHERE table_schema='public' AND table_name=%s",
            (table,),
        ).mappings().all()
        actual = {row["column_name"] for row in rows}
        types = {
            row["column_name"]: row["data_type"]
            for row in rows
            if not _type_ok(table, row["column_name"], row["data_type"])
        }
        nullable = sorted(
            row["column_name"]
            for row in rows
            if row["column_name"] in EXPECTED_NOT_NULL[table] and row["is_nullable"] != "NO"
        )
        generated_id_missing = []
        id_column = GENERATED_ID_COLUMNS.get(table)
        if id_column and id_column in actual:
            id_row = next(row for row in rows if row["column_name"] == id_column)
            default = id_row["column_default"] or ""
            if "nextval(" not in default.lower() and id_row["is_identity"] != "YES":
                generated_id_missing.append(id_column)

        constraints = set()
        constraint_rows = conn.exec_driver_sql(
            "SELECT tc.constraint_type, "
            "string_agg(kcu.column_name, ',' ORDER BY kcu.ordinal_position) AS columns, "
            "ccu.table_name AS foreign_table, "
            "string_agg(ccu.column_name, ',' ORDER BY kcu.ordinal_position) AS foreign_columns "
            "FROM information_schema.table_constraints tc "
            "LEFT JOIN information_schema.key_column_usage kcu "
            "ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema "
            "LEFT JOIN information_schema.constraint_column_usage ccu "
            "ON tc.constraint_name=ccu.constraint_name AND tc.table_schema=ccu.table_schema "
            "WHERE tc.table_schema='public' AND tc.table_name=%s "
            "AND tc.constraint_type IN ('PRIMARY KEY','UNIQUE','FOREIGN KEY') "
            "GROUP BY tc.constraint_name,tc.constraint_type,ccu.table_name",
            (table,),
        ).mappings().all()
        for row in constraint_rows:
            cols = row["columns"] or ""
            kind = row["constraint_type"]
            if kind == "FOREIGN KEY":
                constraints.add(f"FOREIGN KEY({cols})->{row['foreign_table']}({row['foreign_columns'] or ''})")
            else:
                constraints.add(f"{kind}({cols})")
        index_rows = conn.exec_driver_sql(
            "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public' AND tablename=%s",
            (table,),
        ).mappings().all()
        indexes = {row["indexname"] for row in index_rows}
        index_definitions = {row["indexname"]: str(row["indexdef"]).lower() for row in index_rows}
        invalid_indexes = {
            name: index_definitions.get(name, "")
            for name, parts in EXPECTED_INDEX_PARTS.items()
            if name in EXPECTED_INDEXES.get(table, set())
            and (name not in index_definitions or not all(part in index_definitions[name] for part in parts))
        }
        result[table] = {
            "present": sorted(actual),
            "missing": sorted(expected - actual),
            "extra": sorted(actual - expected),
            "incompatible_types": types,
            "unexpected_nullable_columns": nullable,
            "constraints": sorted(constraints),
            "missing_constraints": sorted(EXPECTED_CONSTRAINTS[table] - constraints),
            "indexes": sorted(indexes),
            "missing_indexes": sorted(EXPECTED_INDEXES.get(table, set()) - indexes),
            "incompatible_indexes": invalid_indexes,
            "missing_generated_id_defaults": generated_id_missing,
        }
    return result


def _sqlite_schema(conn) -> dict:
    result = {}
    for table, expected in EXPECTED_COLUMNS.items():
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").mappings().all()
        actual = {row["name"] for row in rows}
        constraints = set()
        indexes = set()
        if rows:
            primary = sorted((row["pk"], row["name"]) for row in rows if row["pk"])
            if primary:
                constraints.add("PRIMARY KEY(" + ",".join(name for _, name in primary) + ")")
            for index in conn.exec_driver_sql(f"PRAGMA index_list({table})").mappings():
                indexes.add(index["name"])
                if index["unique"]:
                    columns = [r["name"] for r in conn.exec_driver_sql(f"PRAGMA index_info({index['name']})").mappings()]
                    constraints.add("UNIQUE(" + ",".join(columns) + ")")
            for fk in conn.exec_driver_sql(f"PRAGMA foreign_key_list({table})").mappings():
                constraints.add(f"FOREIGN KEY({fk['from']})->{fk['table']}({fk['to']})")
        result[table] = {
            "present": sorted(actual),
            "missing": sorted(expected - actual),
            "extra": sorted(actual - expected),
            "incompatible_types": {},
            "unexpected_nullable_columns": [],
            "constraints": sorted(constraints),
            "missing_constraints": sorted(EXPECTED_CONSTRAINTS[table] - constraints),
            "indexes": sorted(indexes),
            "missing_indexes": sorted(EXPECTED_INDEXES.get(table, set()) - indexes),
            "incompatible_indexes": {},
            "missing_generated_id_defaults": [],
        }
    return result


def inspect_schema() -> dict:
    """Inspect columns, types, keys, and ID generation without writing."""
    with engine.connect() as conn:
        if engine.dialect.name == "postgresql":
            return _postgres_schema(conn)
        return _sqlite_schema(conn)


if __name__ == "__main__":
    import json
    print(json.dumps(inspect_schema(), indent=2))
