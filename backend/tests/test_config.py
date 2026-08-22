"""Tests for configuration loading and validation."""

from app.core.config import Settings


def test_default_settings():
    """Settings can be created with defaults."""
    settings = Settings(
        app_env="testing",
        database_url="postgresql+asyncpg://test:test@localhost/test",
    )
    assert settings.app_name == "Transaction Twin"
    assert settings.app_version == "0.1.0"


def test_is_development():
    """is_development property works correctly."""
    settings = Settings(app_env="development", database_url="postgresql+asyncpg://x/x")
    assert settings.is_development is True
    assert settings.is_production is False


def test_is_production():
    """is_production property works correctly."""
    settings = Settings(app_env="production", database_url="postgresql+asyncpg://x/x")
    assert settings.is_production is True
    assert settings.is_development is False


def test_api_prefix():
    """API prefix defaults to /api/v1."""
    settings = Settings(app_env="test", database_url="postgresql+asyncpg://x/x")
    assert settings.api_v1_prefix == "/api/v1"
