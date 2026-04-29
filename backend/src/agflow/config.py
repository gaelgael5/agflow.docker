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

    google_client_id: str = ""
    google_client_secret: str = ""

    # Keycloak OIDC
    auth_mode: str = "local"  # "keycloak" or "local"
    keycloak_url: str = ""
    keycloak_realm: str = ""
    keycloak_client_id: str = ""
    keycloak_client_secret: str = ""

    environment: str = "dev"
    log_level: str = "INFO"
    jwt_expire_hours: int = 24
    api_key_salt: str = ""

    # Base URL of the central Grafana UI (without trailing slash) used to open
    # per-machine log views from the admin UI. Defaults to the public URL routed
    # by the Cloudflare tunnel (LXC 112) towards the agflow-logs LXC (116).
    grafana_url: str = "https://log.yoops.org"

    @property
    def keycloak_base(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
