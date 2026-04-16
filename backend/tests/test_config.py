from __future__ import annotations

import pytest

from agflow.config import Settings


def test_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/test")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.org")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "$2b$12$fakehash")
    monkeypatch.setenv("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")

    settings = Settings()

    assert settings.database_url == "postgresql://u:p@localhost:5432/test"
    assert settings.jwt_secret == "test-secret-key"
    assert settings.admin_email == "admin@example.org"


def test_settings_default_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/test")
    monkeypatch.setenv("JWT_SECRET", "x")
    monkeypatch.setenv("ADMIN_EMAIL", "a@b.c")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "x")
    monkeypatch.setenv("SECRETS_MASTER_KEY", "x")

    settings = Settings()

    assert settings.environment == "dev"
    assert settings.log_level == "INFO"
    assert settings.jwt_expire_hours == 24


def test_settings_requires_secrets_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/test")
    monkeypatch.setenv("JWT_SECRET", "x")
    monkeypatch.setenv("ADMIN_EMAIL", "a@b.c")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "x")
    monkeypatch.setenv("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")

    settings = Settings()
    assert settings.secrets_master_key == "test-master-key-phrase-32chars-ok"
