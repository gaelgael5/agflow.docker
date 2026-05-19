"""Tests pour pitr_config_service — singleton config + remotes join."""
from __future__ import annotations

import pytest

from agflow.services import pitr_config_service
from agflow.services.pitr_config_service import InvalidCronError
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _fresh_db():
    """Re-applique le schéma avant chaque test pour isoler l'état."""
    await reset_schema_and_migrate()


async def test_get_config_returns_seeded_defaults():
    config = await pitr_config_service.get_config()
    assert config.enabled is True
    assert config.basebackup_cron == "0 3 * * *"
    assert config.retention_count == 7
    assert config.remote_connection_ids == []


async def test_update_config_changes_cron():
    await pitr_config_service.update_config(basebackup_cron="0 4 * * *")
    config = await pitr_config_service.get_config()
    assert config.basebackup_cron == "0 4 * * *"


async def test_update_config_invalid_cron_raises():
    with pytest.raises(InvalidCronError):
        await pitr_config_service.update_config(basebackup_cron="not a cron")


async def test_update_config_replaces_remotes(sample_remote_connection_id):
    await pitr_config_service.update_config(
        remote_connection_ids=[sample_remote_connection_id]
    )
    config = await pitr_config_service.get_config()
    assert config.remote_connection_ids == [sample_remote_connection_id]

    # Replace with empty list — must clear out the join table
    await pitr_config_service.update_config(remote_connection_ids=[])
    config = await pitr_config_service.get_config()
    assert config.remote_connection_ids == []


@pytest.fixture
async def sample_remote_connection_id():
    """Insère une remote_backup_connection de test et retourne son UUID.

    Colonnes requises (migration 103_remote_backups.sql) :
      - name TEXT NOT NULL
      - kind TEXT NOT NULL CHECK (kind IN ('sftp', 's3', 'ftps'))
      - config JSONB NOT NULL DEFAULT '{}'
    Les colonnes vault_api_key_id / vault_secret_path sont nullables.
    """
    from agflow.db import pool as _pool

    row = await _pool.fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('test-remote', 'sftp', '{}'::jsonb) RETURNING id"
    )
    return row["id"]
