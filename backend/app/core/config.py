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

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
