from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict

# En production Docker Swarm, les secrets sont mountés sous /run/secrets/.
# En dev local Windows, ce chemin n'existe pas — on le met à None pour
# éviter que Pydantic ne crashe au boot.
_secrets_dir: str | None = "/run/secrets" if os.path.isdir("/run/secrets") else None


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        secrets_dir=_secrets_dir,
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
