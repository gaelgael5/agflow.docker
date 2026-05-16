from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agflow.services import infra_machines_service as svc

_NOW = datetime(2026, 1, 1, tzinfo=UTC)

MACHINE_ID = uuid.uuid4()
TYPE_ID = uuid.uuid4()
_VAULT_NAME = "default"


def _ref(path: str) -> str:
    return f"${{vault://{_VAULT_NAME}:{path}}}"


_ROW = {
    "id": MACHINE_ID, "name": "test", "type_id": TYPE_ID,
    "type_name": "lxc", "category": "lxc",
    "host": "192.168.1.1", "port": 22, "username": "root",
    "password": _ref(f"machines/{MACHINE_ID}/password"),
    "certificate_id": None, "parent_id": None, "user_id": None,
    "environment": None, "children_count": 0,
    "metadata": {}, "status": "not_initialized",
    "required_actions": [], "created_at": _NOW, "updated_at": _NOW,
}


def _patch_default_vault():
    """Patch le lookup du coffre default pour retourner un coffre nommé 'default'."""
    fake = SimpleNamespace(id=uuid.uuid4(), name=_VAULT_NAME)
    return patch(
        "agflow.services.infra_machines_service.harpocrate_vaults_service.get_default",
        AsyncMock(return_value=fake),
    )


@pytest.mark.asyncio
async def test_create_stores_vault_ref() -> None:
    """create() doit pousser le secret puis stocker un vault ref dans la colonne password."""
    with (
        _patch_default_vault(),
        patch("agflow.services.infra_machines_service.vault_client.create_secret") as mock_create,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
        patch("agflow.services.infra_machines_service.execute") as mock_exec,
    ):
        mock_create.return_value = "secret-id-123"
        mock_fetch.side_effect = [
            {"id": MACHINE_ID},  # INSERT RETURNING
            _ROW,                # get_by_id
        ]
        mock_exec.return_value = None

        result = await svc.create(
            type_id=TYPE_ID, host="192.168.1.1", password="s3cr3t",
        )

        mock_create.assert_called_once_with(
            f"machines/{MACHINE_ID}/password", "s3cr3t", vault_name=_VAULT_NAME,
        )
        call_args = mock_exec.call_args[0]
        assert _ref(f"machines/{MACHINE_ID}/password") == call_args[1]
        assert result.has_password is True


@pytest.mark.asyncio
async def test_create_rolls_back_on_vault_failure() -> None:
    """create() doit supprimer la machine si vault.create_secret échoue."""
    with (
        _patch_default_vault(),
        patch("agflow.services.infra_machines_service.vault_client.create_secret") as mock_create,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
        patch("agflow.services.infra_machines_service.execute") as mock_exec,
    ):
        mock_create.side_effect = RuntimeError("vault down")
        mock_fetch.return_value = {"id": MACHINE_ID}
        mock_exec.return_value = None

        with pytest.raises(RuntimeError, match="vault down"):
            await svc.create(type_id=TYPE_ID, host="192.168.1.1", password="s3cr3t")

        delete_calls = [c for c in mock_exec.call_args_list if "DELETE" in str(c)]
        assert len(delete_calls) == 1


@pytest.mark.asyncio
async def test_get_credentials_reads_from_vault() -> None:
    """get_credentials() doit lire le password depuis Harpocrate via resolve_ref."""
    vault_ref = _ref(f"machines/{MACHINE_ID}/password")
    with (
        patch("agflow.services.infra_machines_service.vault_client.resolve_ref") as mock_resolve,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
    ):
        mock_resolve.return_value = "s3cr3t"
        mock_fetch.return_value = {
            "host": "192.168.1.1", "port": 22, "username": "root",
            "password": vault_ref,
            "certificate_id": None,
        }

        creds = await svc.get_credentials(MACHINE_ID)

        mock_resolve.assert_called_once_with(vault_ref)
        assert creds["password"] == "s3cr3t"


@pytest.mark.asyncio
async def test_get_credentials_no_password() -> None:
    """get_credentials() retourne None si pas de vault ref."""
    with patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch:
        mock_fetch.return_value = {
            "host": "192.168.1.1", "port": 22, "username": "root",
            "password": None, "certificate_id": None,
        }
        creds = await svc.get_credentials(MACHINE_ID)
        assert creds["password"] is None


@pytest.mark.asyncio
async def test_update_password_calls_update_secret_when_path_exists() -> None:
    """update() avec ref existant → vault.update_secret sur le même (vault, path)."""
    with (
        patch("agflow.services.infra_machines_service.vault_client.update_secret") as mock_update,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
        patch("agflow.services.infra_machines_service.execute") as mock_exec,
    ):
        existing_ref = _ref(f"machines/{MACHINE_ID}/password")
        mock_update.return_value = None
        mock_fetch.side_effect = [_ROW, {"password": existing_ref}, _ROW]
        mock_exec.return_value = None

        await svc.update(MACHINE_ID, password="new_secret")

        mock_update.assert_called_once_with(
            f"machines/{MACHINE_ID}/password", "new_secret", vault_name=_VAULT_NAME,
        )


@pytest.mark.asyncio
async def test_update_password_calls_create_secret_when_no_path() -> None:
    """update() avec password absent en DB → lookup default + vault.create_secret + UPDATE DB."""
    with (
        _patch_default_vault(),
        patch("agflow.services.infra_machines_service.vault_client.create_secret") as mock_create,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
        patch("agflow.services.infra_machines_service.execute") as mock_exec,
    ):
        mock_create.return_value = "secret-id"
        no_pw_row = {**_ROW, "password": None}
        mock_fetch.side_effect = [no_pw_row, {"password": None}, _ROW]
        mock_exec.return_value = None

        await svc.update(MACHINE_ID, password="new_secret")

        mock_create.assert_called_once_with(
            f"machines/{MACHINE_ID}/password", "new_secret", vault_name=_VAULT_NAME,
        )


@pytest.mark.asyncio
async def test_delete_removes_vault_secret() -> None:
    """delete() doit supprimer le secret Harpocrate après la suppression DB."""
    with (
        patch("agflow.services.infra_machines_service.vault_client.delete_secret") as mock_delete,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
    ):
        existing_ref = _ref(f"machines/{MACHINE_ID}/password")
        mock_delete.return_value = None
        mock_fetch.side_effect = [
            {"password": existing_ref},
            {"id": MACHINE_ID},
        ]

        await svc.delete(MACHINE_ID)

        mock_delete.assert_called_once_with(
            f"machines/{MACHINE_ID}/password", vault_name=_VAULT_NAME,
        )


@pytest.mark.asyncio
async def test_delete_no_vault_ref_skips_vault() -> None:
    """delete() ne doit pas appeler vault si la machine n'a pas de password."""
    with (
        patch("agflow.services.infra_machines_service.vault_client.delete_secret") as mock_delete,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
    ):
        mock_delete.return_value = None
        mock_fetch.side_effect = [
            {"password": None},
            {"id": MACHINE_ID},
        ]

        await svc.delete(MACHINE_ID)

        mock_delete.assert_not_called()
