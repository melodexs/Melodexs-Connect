"""Fail-closed configuration and connection checks for PostgreSQL tests."""

from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy.engine import URL, make_url


@dataclass(frozen=True)
class PostgresTestTarget:
    url: object
    host: str
    database: str
    username: str


def postgres_integration_enabled(env: dict[str, str]) -> bool:
    return env.get("RUN_POSTGRES_INTEGRATION") == "1"


def _parse_postgres_url(raw_url: str, label: str) -> URL:
    if not isinstance(raw_url, str) or not raw_url or raw_url != raw_url.strip():
        raise RuntimeError(f"{label} is missing or malformed")
    try:
        parsed = make_url(raw_url)
    except Exception:
        raise RuntimeError(f"{label} is malformed") from None
    if parsed.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise RuntimeError(f"{label} must use PostgreSQL")
    if not parsed.host or not parsed.database or not parsed.username:
        raise RuntimeError(f"{label} must include a host, database name, and username")
    return parsed


def _canonical_host(host: str) -> str:
    return host.rstrip(".").lower()


def validate_postgres_test_target(env: dict[str, str], application_urls=()) -> PostgresTestTarget:
    """Validate explicit target allowlisting without opening a connection."""
    if env.get("POSTGRES_TEST_DATABASE_VERIFIED") != "YES":
        raise RuntimeError("Set POSTGRES_TEST_DATABASE_VERIFIED=YES only after independently verifying a disposable target")

    expected_host = env.get("POSTGRES_TEST_EXPECTED_HOST", "")
    expected_database = env.get("POSTGRES_TEST_EXPECTED_DATABASE", "")
    expected_username = env.get("POSTGRES_TEST_EXPECTED_USERNAME", "")
    for value, label in (
        (expected_host, "POSTGRES_TEST_EXPECTED_HOST"),
        (expected_database, "POSTGRES_TEST_EXPECTED_DATABASE"),
        (expected_username, "POSTGRES_TEST_EXPECTED_USERNAME"),
    ):
        if not value or value != value.strip():
            raise RuntimeError(f"{label} is required and must not contain surrounding whitespace")

    target = _parse_postgres_url(env.get("POSTGRES_TEST_DATABASE_URL", ""), "POSTGRES_TEST_DATABASE_URL")
    actual_host = _canonical_host(target.host or "")
    if actual_host != _canonical_host(expected_host):
        raise RuntimeError("PostgreSQL test target hostname does not match its expected hostname")
    if target.database != expected_database:
        raise RuntimeError("PostgreSQL test target database does not match its expected database")
    if target.username != expected_username:
        raise RuntimeError("PostgreSQL test target username does not match its expected username")

    # A TLS hostname check binds the configured host to the server certificate.
    query = target.query
    ambiguous_target_fields = {"host", "hostaddr", "dbname", "database", "user", "username", "service", "passfile"}
    if ambiguous_target_fields.intersection(query):
        raise RuntimeError("PostgreSQL test URL contains an ambiguous connection-target override")
    sslmode = query.get("sslmode") if isinstance(query, dict) else None
    if sslmode != "verify-full":
        raise RuntimeError("PostgreSQL test URL must require sslmode=verify-full")

    target_identity = (actual_host, target.database)
    for label, raw_url in application_urls:
        if raw_url is None or raw_url == "":
            continue
        if not isinstance(raw_url, str) or raw_url != raw_url.strip():
            raise RuntimeError(f"Configured application database URL ({label}) is malformed")
        try:
            app_url = make_url(raw_url)
        except Exception:
            raise RuntimeError(f"Configured application database URL ({label}) is malformed") from None
        if app_url.drivername.startswith("postgres"):
            if not app_url.host or not app_url.database:
                raise RuntimeError(f"Configured application database URL ({label}) is ambiguous")
            if (_canonical_host(app_url.host), app_url.database) == target_identity:
                raise RuntimeError("PostgreSQL test target matches a configured application database")
        elif not app_url.drivername.startswith("sqlite"):
            raise RuntimeError(f"Configured application database URL ({label}) uses an unsupported scheme")

    return PostgresTestTarget(
        url=target,
        host=actual_host,
        database=target.database,
        username=target.username,
    )


def verify_connected_postgres_identity(engine, target: PostgresTestTarget) -> None:
    """Check configured host and server-reported database/user before tests."""
    url = engine.url
    if (
        engine.dialect.name != "postgresql"
        or not url.host
        or _canonical_host(url.host) != target.host
        or url.database != target.database
        or url.username != target.username
    ):
        raise RuntimeError("PostgreSQL engine target differs from the approved test target")

    try:
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT current_database(), current_user, inet_server_addr()::text"
            ).one()
    except Exception:
        raise RuntimeError("Could not verify the connected PostgreSQL test database identity") from None
    if row[0] != target.database or row[1] != target.username or not row[2]:
        raise RuntimeError("Connected PostgreSQL database identity does not match the approved test target")
