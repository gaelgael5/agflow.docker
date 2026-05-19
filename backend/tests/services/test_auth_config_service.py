"""Tests pour auth_config_service — get + update."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agflow.db.pool import execute, fetch_one
from agflow.schemas.auth_config import AuthConfigUpdate
from agflow.services import auth_config_service
from agflow.services.auth_config_service import (
    InvalidUrlError,
    VaultNameUnknownError,
)
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _fresh_db():
    await reset_schema_and_migrate()


async def test_get_config_returns_seeded_defaults():
    cfg = await auth_config_service.get_config()
    assert cfg.mode == "local"
    assert cfg.keycloak_url == ""
    assert cfg.keycloak_realm == ""
    assert cfg.keycloak_client_id == ""
    assert cfg.has_secret is False
    assert cfg.vault_name == "default"


async def test_get_config_has_secret_true_when_ref_set():
    """Si la colonne keycloak_client_secret_ref n'est pas vide, has_secret=True."""
    await execute(
        "UPDATE auth_config SET keycloak_client_secret_ref = $1 WHERE id = 1",
        "${vault://default:auth/keycloak/client_secret}",
    )
    cfg = await auth_config_service.get_config()
    assert cfg.has_secret is True


async def test_update_config_changes_mode():
    payload = AuthConfigUpdate(mode="keycloak")
    cfg = await auth_config_service.update_config(payload, actor_user_id=None)
    assert cfg.mode == "keycloak"


async def test_update_config_invalid_url_raises():
    payload = AuthConfigUpdate(keycloak_url="not-a-url")
    with pytest.raises(InvalidUrlError):
        await auth_config_service.update_config(payload, actor_user_id=None)


async def test_update_config_unknown_vault_raises():
    payload = AuthConfigUpdate(vault_name="nonexistent-vault-xyz")
    with patch(
        "agflow.services.auth_config_service.harpocrate_vaults_service.get_by_name",
        new=AsyncMock(return_value=None),
    ), pytest.raises(VaultNameUnknownError):
        await auth_config_service.update_config(payload, actor_user_id=None)


async def test_update_config_pushes_secret_to_vault_when_provided():
    """Quand le payload contient keycloak_client_secret, le service appelle
    update_secret puis stocke la ref dans la colonne."""
    fake_vault = type("V", (), {"name": "default"})()
    with patch(
        "agflow.services.auth_config_service.harpocrate_vaults_service.get_by_name",
        new=AsyncMock(return_value=fake_vault),
    ), patch(
        "agflow.services.auth_config_service.vault_client.update_secret",
        new=AsyncMock(),
    ) as mock_update:
        payload = AuthConfigUpdate(
            keycloak_client_secret="super-secret",
            vault_name="default",
        )
        cfg = await auth_config_service.update_config(payload, actor_user_id=None)

    mock_update.assert_called_once_with(
        "auth/keycloak/client_secret", "super-secret", vault_name="default"
    )
    row = await fetch_one("SELECT keycloak_client_secret_ref FROM auth_config WHERE id = 1")
    assert row["keycloak_client_secret_ref"] == "${vault://default:auth/keycloak/client_secret}"
    assert cfg.has_secret is True


async def test_update_config_creates_secret_if_not_exists():
    """Si update_secret renvoie 404, fallback sur create_secret."""
    from harpocrate.exceptions import VaultHttpError

    fake_vault = type("V", (), {"name": "default"})()
    err_404 = VaultHttpError("not found", status_code=404)
    with patch(
        "agflow.services.auth_config_service.harpocrate_vaults_service.get_by_name",
        new=AsyncMock(return_value=fake_vault),
    ), patch(
        "agflow.services.auth_config_service.vault_client.update_secret",
        new=AsyncMock(side_effect=err_404),
    ), patch(
        "agflow.services.auth_config_service.vault_client.create_secret",
        new=AsyncMock(),
    ) as mock_create:
        payload = AuthConfigUpdate(
            keycloak_client_secret="new-secret",
            vault_name="default",
        )
        await auth_config_service.update_config(payload, actor_user_id=None)

    mock_create.assert_called_once_with(
        "auth/keycloak/client_secret",
        "new-secret",
        description="Keycloak OIDC client_secret",
        vault_name="default",
    )


async def test_update_config_stores_actor_user_id():
    actor = uuid4()
    await execute(
        "INSERT INTO users (id, email, name, role, status) VALUES ($1, 'a@b.c', 'A', 'admin', 'active')",
        actor,
    )
    payload = AuthConfigUpdate(mode="keycloak")
    await auth_config_service.update_config(payload, actor_user_id=actor)
    row = await fetch_one("SELECT updated_by_user_id FROM auth_config WHERE id = 1")
    assert row["updated_by_user_id"] == actor
