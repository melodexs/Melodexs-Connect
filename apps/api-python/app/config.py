from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    port: int = 3000
    node_env: str = "development"
    database_url: str = f"sqlite:///{ROOT / 'apps/api-python/data/test.db'}"
    session_secret: str = "dev-only-insecure-secret"
    cheapdata_public_url: str = "https://melodexs-connect.onrender.com"
    paystack_secret_key: str | None = None
    wisesub_base_url: str = "https://app.wisesub.com.ng/api/partner/v1"
    wisesub_api_key: str | None = None
    wisesub_api_secret: str | None = None
    wisesub_environment: str = "test"
    cheapdata_markup_percent: float = 2
    brevo_api_key: str | None = None
    brevo_from_email: str | None = None
    brevo_from_name: str = "MELODEXS CONNECT"

    @property
    def production(self) -> bool:
        return self.node_env.lower() == "production"


settings = Settings()
if settings.production and len(settings.session_secret) < 32:
    raise RuntimeError("SESSION_SECRET must be at least 32 characters in production")

