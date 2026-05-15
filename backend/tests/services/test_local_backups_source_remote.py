from __future__ import annotations

from uuid import uuid4

import pytest

from agflow.db.pool import execute, fetch_one


@pytest.mark.skip(
    reason="DB integration test — validated post-deploy on LXC 201 (no local Postgres)"
)
@pytest.mark.asyncio
async def test_local_backups_has_source_remote_column(db_pool):
    """After migration 104, the source_remote_connection_id column exists."""
    row = await fetch_one(
        """
        SELECT column_name, is_nullable, data_type
        FROM information_schema.columns
        WHERE table_name = 'local_backups'
          AND column_name = 'source_remote_connection_id'
        """
    )
    assert row is not None
    assert row["is_nullable"] == "YES"
    assert row["data_type"] == "uuid"


@pytest.mark.skip(
    reason="DB integration test — validated post-deploy on LXC 201 (no local Postgres)"
)
@pytest.mark.asyncio
async def test_local_backups_fk_set_null_on_remote_delete(db_pool):
    """If the remote connection is hard-deleted in SQL, the FK SET NULL is applied.

    This test exercises the raw SQL FK guarantee, not the soft-delete path used by
    the service layer. A hard DELETE is intentional here to trigger the ON DELETE SET
    NULL constraint defined in the migration.
    """
    remote_id = uuid4()
    backup_id = uuid4()

    try:
        await execute(
            "INSERT INTO remote_backup_connections (id, name, kind, config) "
            "VALUES ($1, $2, 'sftp', '{}'::jsonb)",
            remote_id,
            f"test-remote-{remote_id}",
        )
        await execute(
            "INSERT INTO local_backups (id, filename, file_path, status, source_remote_connection_id) "
            "VALUES ($1, 'test.sql.gz', '/tmp/test.sql.gz', 'completed', $2)",
            backup_id,
            remote_id,
        )
        await execute("DELETE FROM remote_backup_connections WHERE id = $1", remote_id)

        row = await fetch_one(
            "SELECT source_remote_connection_id FROM local_backups WHERE id = $1",
            backup_id,
        )
        assert row["source_remote_connection_id"] is None
    finally:
        await execute("DELETE FROM local_backups WHERE id = $1", backup_id)
        await execute("DELETE FROM remote_backup_connections WHERE id = $1", remote_id)
