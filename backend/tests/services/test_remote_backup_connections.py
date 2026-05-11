from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    return conn


@pytest.mark.asyncio
async def test_create_connection_stores_creds_in_vault(mock_conn):
    """create_connection appelle vault_client.create_secret avec json.dumps(credentials)."""
    from agflow.services import remote_backup_connections_service as svc

    credentials = {"username": "user", "auth_method": "password", "password": "s3cr3t"}
    connection_id = uuid4()

    with (
        patch.object(svc, "_insert_row", AsyncMock(return_value=None)),
        patch("agflow.services.remote_backup_connections_service.vault_client") as mock_vault,
        patch("agflow.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.harpocrate_vault_api_key_id = "default"
        mock_vault.create_secret = AsyncMock(return_value="secret-uuid")
        # Patch _fetch_row_by_id pour le get_connection appelé après create
        with patch.object(svc, "_fetch_row_by_id", AsyncMock(return_value=None)):
            pass

        result = await svc.create_connection(
            conn=mock_conn,
            name="sftp-prod",
            kind="sftp",
            config={"host": "sftp.example.com", "port": 22},
            credentials=credentials,
        )

    mock_vault.create_secret.assert_called_once()
    call_args = mock_vault.create_secret.call_args
    assert call_args.args[0].startswith("remote-backups/")
    stored = json.loads(call_args.args[1])
    assert stored["password"] == "s3cr3t"


@pytest.mark.asyncio
async def test_create_connection_rolls_back_vault_on_db_failure(mock_conn):
    """Si l'insert DB échoue après vault.create_secret, delete_secret est appelé."""
    from agflow.services import remote_backup_connections_service as svc

    with (
        patch.object(svc, "_insert_row", AsyncMock(side_effect=Exception("DB down"))),
        patch("agflow.services.remote_backup_connections_service.vault_client") as mock_vault,
        patch("agflow.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.harpocrate_vault_api_key_id = "default"
        mock_vault.create_secret = AsyncMock(return_value="secret-uuid")
        mock_vault.delete_secret = AsyncMock()

        with pytest.raises(Exception, match="DB down"):
            await svc.create_connection(
                conn=mock_conn,
                name="sftp-prod",
                kind="sftp",
                config={},
                credentials={"username": "u", "password": "p"},
            )

    mock_vault.delete_secret.assert_called_once()


@pytest.mark.asyncio
async def test_list_connections_never_calls_vault(mock_conn):
    """list_connections ne doit PAS appeler vault_client."""
    from agflow.services import remote_backup_connections_service as svc

    with (
        patch.object(svc, "_fetch_all_rows", AsyncMock(return_value=[])),
        patch("agflow.services.remote_backup_connections_service.vault_client") as mock_vault,
    ):
        await svc.list_connections(mock_conn)
        mock_vault.get_secret.assert_not_called()


@pytest.mark.asyncio
async def test_delete_connection_soft_deletes_then_removes_vault(mock_conn):
    """delete_connection soft-delete DB en premier, puis delete_secret best-effort."""
    from agflow.services import remote_backup_connections_service as svc

    conn_id = uuid4()
    row = {
        "id": conn_id, "name": "test", "kind": "sftp", "config": {},
        "vault_api_key_id": "default", "vault_secret_path": f"remote-backups/{conn_id}",
        "has_credentials": True, "created_at": None, "updated_at": None,
    }

    with (
        patch.object(svc, "_fetch_row_by_id", AsyncMock(return_value=row)),
        patch.object(svc, "_soft_delete_row", AsyncMock()),
        patch("agflow.services.remote_backup_connections_service.vault_client") as mock_vault,
    ):
        mock_vault.delete_secret = AsyncMock()
        await svc.delete_connection(mock_conn, conn_id)

    mock_vault.delete_secret.assert_called_once_with(f"remote-backups/{conn_id}")
