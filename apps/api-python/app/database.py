from contextlib import contextmanager
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .config import settings, ROOT

database_url = settings.database_url or f"sqlite:///{ROOT / 'apps/api-python/data/local.db'}"
# SQLAlchemy otherwise selects psycopg2 for generic PostgreSQL URLs, while the
# application intentionally installs psycopg v3.
if database_url.startswith("postgres://"):
    database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
elif database_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def q(session, statement: str, params: dict | None = None):
    return session.execute(text(statement), params or {})


def init_schema():
    # All statements are additive and match the existing PostgreSQL tables.
    with engine.begin() as conn:
        if database_url.startswith("sqlite"):
            auto = "INTEGER PRIMARY KEY AUTOINCREMENT"
            bool_type = "INTEGER"
            money_type = "NUMERIC"
            timestamp_type = "TEXT"
            now = "CURRENT_TIMESTAMP"
        else:
            auto = "SERIAL PRIMARY KEY"
            bool_type = "INTEGER"
            money_type = "DOUBLE PRECISION"
            timestamp_type = "TIMESTAMP"
            now = "CURRENT_TIMESTAMP"
        conn.execute(text(f"""CREATE TABLE IF NOT EXISTS users (
            id {auto}, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
            purchase_pin TEXT, balance {money_type} NOT NULL DEFAULT 0,
            virtual_account_number TEXT, virtual_bank_name TEXT,
            kyc_status TEXT NOT NULL DEFAULT 'pending', is_admin {bool_type} NOT NULL DEFAULT 0,
            reset_token_hash TEXT, reset_token_expires_at BIGINT, created_at {timestamp_type} NOT NULL DEFAULT {now})"""))
        conn.execute(text(f"""CREATE TABLE IF NOT EXISTS data_plans (
            id {auto}, network TEXT NOT NULL, plan TEXT NOT NULL, provider_cost {money_type} NOT NULL DEFAULT 0,
            plan_name TEXT, status TEXT,
            selling_price {money_type} NOT NULL, active {bool_type} NOT NULL DEFAULT 1, provider TEXT,
            provider_code TEXT, provider_package_code TEXT, provider_package_name TEXT, data_size TEXT,
            validity TEXT, source TEXT, last_synced_at {timestamp_type}, created_at {timestamp_type} NOT NULL DEFAULT {now},
            updated_at {timestamp_type} NOT NULL DEFAULT {now}, UNIQUE(network, plan))"""))
        # Additive catalog controls. Existing active values remain the admin's
        # enable/disable decision; provider availability is tracked separately.
        if engine.dialect.name != "sqlite":
            conn.execute(text("ALTER TABLE data_plans ADD COLUMN IF NOT EXISTS provider_available INTEGER NOT NULL DEFAULT 1"))
            conn.execute(text("ALTER TABLE data_plans ADD COLUMN IF NOT EXISTS selling_price_override DOUBLE PRECISION"))
            conn.execute(text("ALTER TABLE data_plans ADD COLUMN IF NOT EXISTS category TEXT"))
            conn.execute(text("ALTER TABLE data_plans ADD COLUMN IF NOT EXISTS provider_category TEXT"))
            conn.execute(text("ALTER TABLE data_plans ADD COLUMN IF NOT EXISTS sync_error TEXT"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_data_plans_provider_package ON data_plans(source, provider_code, provider_package_code) WHERE source IS NOT NULL AND provider_code IS NOT NULL AND provider_package_code IS NOT NULL"))
            conn.execute(text(f"""CREATE TABLE IF NOT EXISTS data_plan_sync_runs (
                id {auto}, started_at {timestamp_type} NOT NULL DEFAULT {now},
                finished_at {timestamp_type}, outcome TEXT NOT NULL,
                added INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL DEFAULT 0,
                unavailable INTEGER NOT NULL DEFAULT 0, errors TEXT)"""))
        # Multi-provider platform registry. WiseSub is enabled by default;
        # additional providers stay disabled until an admin enables them.
        conn.execute(text(f"""CREATE TABLE IF NOT EXISTS providers (
            slug TEXT PRIMARY KEY, name TEXT NOT NULL,
            enabled {bool_type} NOT NULL DEFAULT 0,
            status TEXT, last_check_at {timestamp_type}, last_check_detail TEXT,
            updated_at {timestamp_type} NOT NULL DEFAULT {now})"""))
        conn.execute(text(f"""CREATE TABLE IF NOT EXISTS transactions (
            id {auto}, user_id INTEGER NOT NULL, type TEXT NOT NULL, amount {money_type} NOT NULL,
            status TEXT NOT NULL, reference TEXT, description TEXT, created_at {timestamp_type} NOT NULL DEFAULT {now},
            FOREIGN KEY(user_id) REFERENCES users(id))"""))
        if engine.dialect.name != "sqlite":
            conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS idempotency_key TEXT"))
            conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS provider_reference TEXT"))
            conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS provider TEXT"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_reference ON transactions(reference) WHERE reference IS NOT NULL"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_user_idempotency ON transactions(user_id,idempotency_key) WHERE idempotency_key IS NOT NULL"))
        # Saved recipient numbers for faster repeat purchases. Tied to the
        # owning account; never shared between users.
        conn.execute(text(f"""CREATE TABLE IF NOT EXISTS favorite_recipients (
            id {auto}, user_id INTEGER NOT NULL, label TEXT, phone TEXT NOT NULL,
            network TEXT, created_at {timestamp_type} NOT NULL DEFAULT {now},
            FOREIGN KEY(user_id) REFERENCES users(id))"""))
        conn.execute(text("CREATE TABLE IF NOT EXISTS sessions (sid TEXT PRIMARY KEY, sess TEXT NOT NULL, expire BIGINT NOT NULL)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sessions_expire ON sessions(expire)"))


@contextmanager
def db_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def apply_catalog_test_schema():
    """Test-only schema additions; production uses reviewed SQL migrations."""
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(data_plans)")}
            for name, kind in (("provider_available", "INTEGER NOT NULL DEFAULT 1"), ("selling_price_override", "NUMERIC"), ("category", "TEXT"), ("provider_category", "TEXT"), ("sync_error", "TEXT")):
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE data_plans ADD COLUMN {name} {kind}")
            conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_data_plans_provider_package ON data_plans(source, provider_code, provider_package_code) WHERE source IS NOT NULL AND provider_code IS NOT NULL AND provider_package_code IS NOT NULL")
            tx_existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(transactions)")}
            for name in ("idempotency_key", "provider_reference", "provider"):
                if name not in tx_existing:
                    conn.exec_driver_sql(f"ALTER TABLE transactions ADD COLUMN {name} TEXT")
            conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS providers (slug TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, status TEXT, last_check_at TEXT, last_check_detail TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_reference ON transactions(reference) WHERE reference IS NOT NULL")
            conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_user_idempotency ON transactions(user_id,idempotency_key) WHERE idempotency_key IS NOT NULL")
            conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_reset_token_hash ON users(reset_token_hash) WHERE reset_token_hash IS NOT NULL")
            conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS data_plan_sync_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TEXT, outcome TEXT NOT NULL, added INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL DEFAULT 0, unavailable INTEGER NOT NULL DEFAULT 0, errors TEXT)")

