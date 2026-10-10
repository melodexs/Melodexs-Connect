from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    port: int = 3000
    node_env: str = "development"
    # SQLite is a local/test convenience only. Production requires the same
    # PostgreSQL DATABASE_URL used by the existing API.
    database_url: str | None = None
    session_secret: str = "dev-only-insecure-secret"
    cheapdata_public_url: str = "https://melodexs-connect.onrender.com"
    paystack_secret_key: str | None = None
    wisesub_base_url: str = "https://app.wisesub.com.ng/api/partner/v1"
    wisesub_api_key: str | None = None
    wisesub_api_secret: str | None = None
    wisesub_environment: str = "test"
    # Provider docs show a successful state but do not define terminal failure
    # semantics. Keep automated refunds disabled until staging confirms them.
    wisesub_failure_status_confirmed: bool = False
    cheapdata_markup_percent: float = 2
    brevo_api_key: str | None = None
    brevo_from_email: str | None = None
    brevo_from_name: str = "MELODEXS CONNECT"

    @property
    def production(self) -> bool:
        return self.node_env.lower() == "production"


settings = Settings()
if settings.production:
    missing = []
    if not settings.database_url:
        missing.append("DATABASE_URL")
    elif not settings.database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("DATABASE_URL must point to PostgreSQL in production")
    if not settings.session_secret or len(settings.session_secret) < 32:
        missing.append("SESSION_SECRET (at least 32 characters)")
    if missing:
        raise RuntimeError("Missing or invalid production configuration: " + ", ".join(missing))

