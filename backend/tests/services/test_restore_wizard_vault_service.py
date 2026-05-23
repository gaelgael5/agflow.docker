from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agflow.services.restore_wizard_vault_service import (
    InvalidVaultCredentialsError,
    list_vault_secrets_by_prefix,
    test_vault_connection,
)


class _FakeSecretItem:
    def __init__(self, name: str, tags: list[str] | None = None) -> None:
        self.name = name
        self.tags = tags


class _FakeSecretsClient:
    def list_secrets(self, limit: int = 200):
        result = MagicMock()
        result.secrets = [
            _FakeSecretItem("certificates/id_prod", ["prod", "ssh"]),
            _FakeSecretItem("remote-backups/sftp-prod", ["prod"]),
            _FakeSecretItem("other/secret"),
        ]
        return result


@pytest.mark.asyncio
async def test_test_vault_connection_ok(monkeypatch):
    fake_client = MagicMock()
    fake_client.secrets = _FakeSecretsClient()
    with patch(
        "agflow.services.restore_wizard_vault_service.VaultClient",
        return_value=fake_client,
    ):
        # Ne doit pas lever d'exception
        await test_vault_connection("https://vault.example.com", "valid-key")


@pytest.mark.asyncio
async def test_test_vault_connection_invalid_key(monkeypatch):
    from harpocrate.exceptions import VaultHttpError

    fake_client = MagicMock()
    err = VaultHttpError.__new__(VaultHttpError)
    err.status_code = 401
    fake_client.secrets.list_secrets.side_effect = err
    with patch(
        "agflow.services.restore_wizard_vault_service.VaultClient",
        return_value=fake_client,
    ):
        with pytest.raises(InvalidVaultCredentialsError):
            await test_vault_connection("https://vault.example.com", "bad-key")


@pytest.mark.asyncio
async def test_list_vault_secrets_by_prefix_filters_correctly(monkeypatch):
    fake_client = MagicMock()
    fake_client.secrets = _FakeSecretsClient()
    with patch(
        "agflow.services.restore_wizard_vault_service.VaultClient",
        return_value=fake_client,
    ):
        items = await list_vault_secrets_by_prefix(
            "https://vault.example.com", "valid-key", "certificates"
        )
    assert len(items) == 1
    assert items[0].name == "certificates/id_prod"
    assert "prod" in items[0].tags


@pytest.mark.asyncio
async def test_list_vault_secrets_by_prefix_returns_all_when_prefix_empty(monkeypatch):
    fake_client = MagicMock()
    fake_client.secrets = _FakeSecretsClient()
    with patch(
        "agflow.services.restore_wizard_vault_service.VaultClient",
        return_value=fake_client,
    ):
        items = await list_vault_secrets_by_prefix(
            "https://vault.example.com", "valid-key", ""
        )
    assert len(items) == 3
