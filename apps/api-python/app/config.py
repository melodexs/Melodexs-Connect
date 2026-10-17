from pathlib import Path
from urllib.parse import urlsplit
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]
# Matches the fallback endpoint in the active Node WiseSub service.
WISESUB_LIVE_BASE_URL = "https://app.wisesub.com.ng/api/partner/v1"
_ALLOWED_RUNTIME_ENVIRONMENTS = {"development", "test", "production"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    port: int = 3000
    # Require the launcher to distinguish a local/test process from a deploy.
    node_env: str | None = None
    # SQLite is a local/test convenience only. Production requires the same
    # PostgreSQL DATABASE_URL used by the existing API.
    database_url: str | None = None
    session_secret: str = "dev-only-insecure-secret"
    cheapdata_public_url: str = "https://melodexs-connect.onrender.com"
    paystack_secret_key: str | None = None
    wisesub_base_url: str = WISESUB_LIVE_BASE_URL
    wisesub_api_key: str | None = None
    wisesub_api_secret: str | None = None
    wisesub_environment: str = "test"
    # Provider docs show a successful state but do not define terminal failure
    # semantics. Keep automated refunds disabled until staging confirms them.
    wisesub_failure_status_confirmed: bool = False
    cheapdata_markup_percent: float = 2
    # Multi-provider fulfillment platform. Routing stays WiseSub-only
    # until an admin deliberately enables it after a second provider is
    # configured, enabled and verified.
    multi_provider_routing_enabled: bool = False
    meledata_api_key: str | None = None
    rizpay_api_key: str | None = None
    rizpay_base_url: str | None = None
    gndata_api_key: str | None = None
    gndata_base_url: str | None = None
    brevo_api_key: str | None = None
    brevo_from_email: str | None = None
    brevo_from_name: str = "MELODEXS CONNECT"

    @property
    def production(self) -> bool:
        return (self.node_env or "").strip().lower() == "production"


settings = Settings()


def normalize_runtime_environment(config: Settings) -> str:
    """Require an explicit, recognized runtime mode and normalize its spelling."""
    if "node_env" not in config.model_fields_set:
        raise RuntimeError("NODE_ENV must be explicitly set to development, test, or production")
    environment = (config.node_env or "").strip().lower()
    if environment not in _ALLOWED_RUNTIME_ENVIRONMENTS:
        raise RuntimeError("NODE_ENV must be explicitly set to development, test, or production")
    config.node_env = environment
    return environment


normalize_runtime_environment(settings)
# This boot-time mode cannot be changed by mutating the Settings object later.
PRODUCTION_MODE = settings.production


def _production_required(config: Settings, production_required: bool | None) -> bool:
    return PRODUCTION_MODE or config.production if production_required is None else production_required


def validate_wisesub_environment(
    config: Settings, production_required: bool | None = None
) -> None:
    """Require an explicit, unpadded live mode for production requests."""
    raw_environment = config.wisesub_environment
    if not isinstance(raw_environment, str) or raw_environment != raw_environment.strip() or raw_environment.lower() not in {"test", "live"}:
        raise RuntimeError("WISESUB_ENVIRONMENT must be test or live")
    if not _production_required(config, production_required):
        return
    if "wisesub_environment" not in config.model_fields_set:
        raise RuntimeError("Production requires WISESUB_ENVIRONMENT=live")
    if raw_environment.lower() != "live":
        raise RuntimeError("Production requires WISESUB_ENVIRONMENT=live")


def validate_wisesub_base_url(
    config: Settings, production_required: bool | None = None
) -> str:
    """Restrict production credentials to the endpoint used by the Node API."""
    raw_url = config.wisesub_base_url
    if not isinstance(raw_url, str) or not raw_url or raw_url != raw_url.strip():
        raise RuntimeError("WISESUB_BASE_URL is invalid")
    if not _production_required(config, production_required):
        return raw_url.rstrip("/")
    try:
        expected = urlsplit(WISESUB_LIVE_BASE_URL)
        parsed = urlsplit(raw_url)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError as exc:
        raise RuntimeError("WISESUB_BASE_URL is invalid") from exc
    if (
        parsed.scheme.lower() != "https"
        or (hostname or "").lower() != expected.hostname
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != expected.path
        or parsed.query
        or parsed.fragment
        or raw_url not in (WISESUB_LIVE_BASE_URL, WISESUB_LIVE_BASE_URL + "/")
    ):
        raise RuntimeError("Production requires the approved WiseSub endpoint")
    return WISESUB_LIVE_BASE_URL


def validate_wisesub_configuration(
    config: Settings, production_required: bool | None = None
) -> str:
    validate_wisesub_environment(config, production_required)
    return validate_wisesub_base_url(config, production_required)


def wisesub_base_url() -> str:
    return validate_wisesub_configuration(settings)


def wisesub_recipient(phone: str) -> str:
    """Use the test recipient only outside a production runtime."""
    validate_wisesub_configuration(settings)
    environment = settings.wisesub_environment.lower()
    if PRODUCTION_MODE:
        return phone
    if environment == "test":
        return "08011111111"
    if environment == "live":
        return phone
    raise RuntimeError("WISESUB_ENVIRONMENT must be test or live")


validate_wisesub_configuration(settings)
if PRODUCTION_MODE:
    missing = []
    if not settings.database_url:
        missing.append("DATABASE_URL")
    elif not settings.database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("DATABASE_URL must point to PostgreSQL in production")
    if not settings.session_secret or len(settings.session_secret) < 32:
        missing.append("SESSION_SECRET (at least 32 characters)")
    if missing:
        raise RuntimeError("Missing or invalid production configuration: " + ", ".join(missing))

