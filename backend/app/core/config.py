"""Core configuration module.

Loads settings from environment variables using pydantic-settings.
Never hardcode secrets — use .env files for local development.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "Transaction Twin"
    app_version: str = "0.1.0"
    app_env: str = "development"
    log_level: str = "INFO"

    # API
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = (
        "postgresql+asyncpg://transaction_twin:transaction_twin@localhost:5432/transaction_twin"
    )

    # Razorpay (future — placeholders only)
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""

    # LLM (future — placeholder only)
    llm_api_key: str = ""
    llm_provider: str = "gemini"

    # Gemini
    gemini_api_key: str = ""

    # CORS
    cors_origins: str = "http://localhost:3000"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Authentication
    jwt_secret_key: str = "dev-only-insecure-key-must-override-in-production-19ad87"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_testing(self) -> bool:
        return self.app_env == "testing"


# Known insecure development-only JWT secret.
# Must match the default value in Settings.jwt_secret_key.
_INSECURE_DEV_JWT_SECRET = "dev-only-insecure-key-must-override-in-production-19ad87"


def validate_production_settings(settings: Settings) -> None:
    """Fail-fast validation for production environment.

    Raises RuntimeError if the application is configured for production
    but has an insecure or missing JWT secret key.

    This function is intentionally called during startup, not at import time,
    so that tests and development environments are not affected.
    """
    if not settings.is_production:
        return

    if (
        not settings.jwt_secret_key
        or settings.jwt_secret_key == _INSECURE_DEV_JWT_SECRET
    ):
        raise RuntimeError(
            "FATAL: JWT_SECRET_KEY is missing or set to the insecure "
            "development default. Production requires a strong, unique "
            "secret key. Set the JWT_SECRET_KEY environment variable to a "
            "secure random value (at least 32 characters). "
            "Application startup aborted."
        )

    if len(settings.jwt_secret_key) < 32:
        raise RuntimeError(
            "FATAL: JWT_SECRET_KEY is too short. Production requires a "
            "secret key of at least 32 characters. "
            "Application startup aborted."
        )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
