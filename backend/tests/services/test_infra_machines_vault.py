from __future__ import annotations
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import pytest
from agflow.services import infra_machines_service as svc

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

MACHINE_ID = uuid.uuid4()
TYPE_ID = uuid.uuid4()

_ROW = {
    "id": MACHINE_ID, "name": "test", "type_id": TYPE_ID,
    "type_name": "lxc", "category": "lxc",
    "host": "192.168.1.1", "port": 22, "username": "root",
    "password": f"${{vault://HARPOCRATE_KEY:machines/{MACHINE_ID}/password}}",
    "certificate_id": None, "parent_id": None, "user_id": None,
    "environment": None, "children_count": 0,
    "metadata": {}, "status": "not_initialized",
    "required_actions": [], "created_at": _NOW, "updated_at": _NOW,
}


@pytest.mark.asyncio
async def test_create_stores_vault_ref():
    """create() doit stocker un vault ref dans la colonne password."""
    with (
        patch("agflow.services.infra_machines_service.vault_client") as mock_vault,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
        patch("agflow.services.infra_machines_service.execute") as mock_exec,
    ):
        mock_vault.create_secret = AsyncMock(return_value="secret-id-123")
        mock_fetch.side_effect = [
            {"id": MACHINE_ID},  # INSERT RETURNING
            _ROW,                # get_by_id
        ]
        mock_exec.return_value = None

        result = await svc.create(
            type_id=TYPE_ID, host="192.168.1.1", password="s3cr3t"
        )

        mock_vault.create_secret.assert_called_once_with(
            f"machines/{MACHINE_ID}/password", "s3cr3t"
        )
        call_args = mock_exec.call_args[0]
        assert f"machines/{MACHINE_ID}/password" in call_args[1]
        assert result.has_password is True


@pytest.mark.asyncio
async def test_create_rolls_back_on_vault_failure():
    """create() doit supprimer la machine si vault.create_secret échoue."""
    with (
        patch("agflow.services.infra_machines_service.vault_client") as mock_vault,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
        patch("agflow.services.infra_machines_service.execute") as mock_exec,
    ):
        mock_vault.create_secret = AsyncMock(side_effect=RuntimeError("vault down"))
        mock_fetch.return_value = {"id": MACHINE_ID}
        mock_exec.return_value = None

        with pytest.raises(RuntimeError, match="vault down"):
            await svc.create(type_id=TYPE_ID, host="192.168.1.1", password="s3cr3t")

        # La machine doit être supprimée (rollback)
        delete_calls = [c for c in mock_exec.call_args_list if "DELETE" in str(c)]
        assert len(delete_calls) == 1


@pytest.mark.asyncio
async def test_get_credentials_reads_from_vault():
    """get_credentials() doit lire le password depuis Harpocrate."""
    with (
        patch("agflow.services.infra_machines_service.vault_client") as mock_vault,
        patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch,
    ):
        mock_vault.get_secret = AsyncMock(return_value="s3cr3t")
        mock_fetch.return_value = {
            "host": "192.168.1.1", "port": 22, "username": "root",
            "password": f"${{vault://HARPOCRATE_KEY:machines/{MACHINE_ID}/password}}",
            "certificate_id": None,
        }

        creds = await svc.get_credentials(MACHINE_ID)

        mock_vault.get_secret.assert_called_once_with(
            f"machines/{MACHINE_ID}/password"
        )
        assert creds["password"] == "s3cr3t"


@pytest.mark.asyncio
async def test_get_credentials_no_password():
    """get_credentials() retourne None si pas de vault ref."""
    with patch("agflow.services.infra_machines_service.fetch_one") as mock_fetch:
        mock_fetch.return_value = {
            "host": "192.168.1.1", "port": 22, "username": "root",
            "password": None, "certificate_id": None,
        }
        creds = await svc.get_credentials(MACHINE_ID)
        assert creds["password"] is None
