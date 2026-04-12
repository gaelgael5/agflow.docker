from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    jwt_secret: str
    admin_email: str
    admin_password_hash: str
    secrets_master_key: str

    redis_url: str = "redis://localhost:6379/0"
    environment: str = "dev"
    log_level: str = "INFO"
    jwt_expire_hours: int = 24
    api_key_salt: str = ""


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
