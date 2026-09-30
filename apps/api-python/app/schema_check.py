from .config import settings
from .database import engine

EXPECTED = {
    "users": {"id", "name", "email", "phone", "password", "purchase_pin", "balance", "virtual_account_number", "virtual_bank_name", "kyc_status", "is_admin", "reset_token_hash", "reset_token_expires_at", "created_at"},
    "data_plans": {"id", "plan_name", "network", "plan", "provider_cost", "selling_price", "active", "provider", "provider_code", "provider_package_code", "provider_package_name", "data_size", "validity", "source", "status", "last_synced_at", "created_at", "updated_at"},
    "transactions": {"id", "user_id", "type", "amount", "status", "reference", "description", "created_at"},
    "sessions": {"sid", "sess", "expire"},
}


def inspect_schema() -> dict:
    result = {}
    with engine.connect() as conn:
        for table, expected in EXPECTED.items():
            if settings.database_url.startswith("postgres"):
                rows = conn.exec_driver_sql("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s", (table,)).scalars().all()
            else:
                rows = [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").all()]
            actual = set(rows)
            result[table] = {"present": sorted(actual), "missing": sorted(expected - actual), "extra": sorted(actual - expected)}
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(inspect_schema(), indent=2))
