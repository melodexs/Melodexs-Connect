from contextlib import contextmanager
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def q(session, statement: str, params: dict | None = None):
    return session.execute(text(statement), params or {})


def init_schema():
    # All statements are additive and match the existing PostgreSQL tables.
    with engine.begin() as conn:
        if settings.database_url.startswith("sqlite"):
            auto = "INTEGER PRIMARY KEY AUTOINCREMENT"
            bool_type = "INTEGER"
            now = "CURRENT_TIMESTAMP"
        else:
            auto = "SERIAL PRIMARY KEY"
            bool_type = "INTEGER"
            now = "CURRENT_TIMESTAMP"
        conn.execute(text(f"""CREATE TABLE IF NOT EXISTS users (
            id {auto}, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
            purchase_pin TEXT, balance NUMERIC NOT NULL DEFAULT 0,
            virtual_account_number TEXT, virtual_bank_name TEXT,
            kyc_status TEXT NOT NULL DEFAULT 'pending', is_admin {bool_type} NOT NULL DEFAULT 0,
            reset_token_hash TEXT, reset_token_expires_at BIGINT, created_at TEXT NOT NULL DEFAULT {now})"""))
        conn.execute(text(f"""CREATE TABLE IF NOT EXISTS data_plans (
            id {auto}, network TEXT NOT NULL, plan TEXT NOT NULL, provider_cost NUMERIC NOT NULL DEFAULT 0,
            plan_name TEXT, status TEXT,
            selling_price NUMERIC NOT NULL, active {bool_type} NOT NULL DEFAULT 1, provider TEXT,
            provider_code TEXT, provider_package_code TEXT, provider_package_name TEXT, data_size TEXT,
            validity TEXT, source TEXT, last_synced_at TEXT, created_at TEXT NOT NULL DEFAULT {now},
            updated_at TEXT NOT NULL DEFAULT {now}, UNIQUE(network, plan))"""))
        conn.execute(text(f"""CREATE TABLE IF NOT EXISTS transactions (
            id {auto}, user_id INTEGER NOT NULL, type TEXT NOT NULL, amount NUMERIC NOT NULL,
            status TEXT NOT NULL, reference TEXT, description TEXT, created_at TEXT NOT NULL DEFAULT {now})"""))
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

