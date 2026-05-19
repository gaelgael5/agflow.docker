"""Tests pour pitr_basebackup_pushes_service — push + prune."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agflow.db.pool import execute, fetch_one
from agflow.services import pitr_basebackup_pushes_service
from agflow.services.pitr_basebackup_pushes_service import PushNotFoundError
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


async def _seed_basebackup_with_remote() -> tuple:
    """Insert one basebackup + one remote + a pending push.

    Returns (bb_id, remote_id, push_id).
    """
    await reset_schema_and_migrate()
    bb = await fetch_one(
        "INSERT INTO pitr_basebackups (pgbackrest_label, started_at, completed_at, status) "
        "VALUES ('20260520-030000F', now(), now(), 'ok') RETURNING id"
    )
    remote = await fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('test-remote', 'sftp', '{}'::jsonb) RETURNING id"
    )
    push = await fetch_one(
        "INSERT INTO pitr_basebackup_pushes (basebackup_id, remote_connection_id, status) "
        "VALUES ($1, $2, 'pending') RETURNING id",
        bb["id"],
        remote["id"],
    )
    return bb["id"], remote["id"], push["id"]


# ---------------------------------------------------------------------------
# push_basebackup
# ---------------------------------------------------------------------------


async def test_push_basebackup_marks_ok_on_success():
    bb_id, remote_id, push_id = await _seed_basebackup_with_remote()

    fake_provider = AsyncMock()
    # upload_stream(path, filename, source) → int (bytes written)
    fake_provider.upload_stream = AsyncMock(return_value=1024)

    with patch(
        "agflow.services.pitr_basebackup_pushes_service._provider_for",
        new=AsyncMock(return_value=fake_provider),
    ):
        await pitr_basebackup_pushes_service.push_basebackup(bb_id, remote_id)

    row = await fetch_one(
        "SELECT status, remote_path, size_bytes FROM pitr_basebackup_pushes WHERE id = $1",
        push_id,
    )
    assert row["status"] == "ok"
    assert row["remote_path"] == "pitr/20260520-030000F.tar.gz"
    assert row["size_bytes"] == 1024


async def test_push_basebackup_marks_failed_on_provider_error():
    bb_id, remote_id, push_id = await _seed_basebackup_with_remote()

    fake_provider = AsyncMock()
    fake_provider.upload_stream = AsyncMock(side_effect=RuntimeError("network down"))

    with patch(
        "agflow.services.pitr_basebackup_pushes_service._provider_for",
        new=AsyncMock(return_value=fake_provider),
    ), pytest.raises(RuntimeError, match="network down"):
        await pitr_basebackup_pushes_service.push_basebackup(bb_id, remote_id)

    row = await fetch_one(
        "SELECT status, error FROM pitr_basebackup_pushes WHERE id = $1",
        push_id,
    )
    assert row["status"] == "failed"
    assert "network down" in (row["error"] or "")


async def test_push_basebackup_idempotent_when_already_ok():
    bb_id, remote_id, push_id = await _seed_basebackup_with_remote()
    # Manually mark as ok
    await execute(
        "UPDATE pitr_basebackup_pushes SET status = 'ok' WHERE id = $1", push_id
    )

    fake_provider = AsyncMock()
    fake_provider.upload_stream = AsyncMock()

    with patch(
        "agflow.services.pitr_basebackup_pushes_service._provider_for",
        new=AsyncMock(return_value=fake_provider),
    ):
        await pitr_basebackup_pushes_service.push_basebackup(bb_id, remote_id)

    # Provider must NOT have been called
    fake_provider.upload_stream.assert_not_called()


async def test_push_basebackup_404_if_push_not_found():
    await reset_schema_and_migrate()
    with pytest.raises(PushNotFoundError):
        await pitr_basebackup_pushes_service.push_basebackup(uuid4(), uuid4())


# ---------------------------------------------------------------------------
# _prune_old_basebackups
# ---------------------------------------------------------------------------


async def test_prune_old_basebackups_returns_count_deleted():
    """pgbackrest info reports 1 alive label; DB has 3 OK → 2 are deleted."""
    await reset_schema_and_migrate()
    for label in ("20260518-030000F", "20260519-030000F", "20260520-030000F"):
        await execute(
            "INSERT INTO pitr_basebackups (pgbackrest_label, started_at, completed_at, status) "
            "VALUES ($1, now(), now(), 'ok')",
            label,
        )

    info_json = json.dumps(
        [{"name": "agflow", "backup": [{"label": "20260520-030000F"}]}]
    )
    mock_exec = AsyncMock()
    mock_exec.side_effect = [
        (0, "", ""),          # expire command
        (0, info_json, ""),   # info command
    ]
    with patch(
        "agflow.services.pitr_basebackup_pushes_service._pg_exec", mock_exec
    ):
        deleted = await pitr_basebackup_pushes_service._prune_old_basebackups(
            retention_count=7
        )

    assert deleted == 2
    # Only the alive label should remain in DB
    remaining = await fetch_one(
        "SELECT count(*)::int AS n FROM pitr_basebackups WHERE status = 'ok'"
    )
    assert remaining["n"] == 1


async def test_prune_old_basebackups_defensive_empty_info():
    """If pgbackrest info returns an empty backup list, DB must not be touched."""
    await reset_schema_and_migrate()
    await execute(
        "INSERT INTO pitr_basebackups (pgbackrest_label, started_at, completed_at, status) "
        "VALUES ('20260520-030000F', now(), now(), 'ok')"
    )

    info_json = json.dumps([{"name": "agflow", "backup": []}])
    mock_exec = AsyncMock()
    mock_exec.side_effect = [
        (0, "", ""),          # expire command
        (0, info_json, ""),   # info command
    ]
    with patch(
        "agflow.services.pitr_basebackup_pushes_service._pg_exec", mock_exec
    ):
        deleted = await pitr_basebackup_pushes_service._prune_old_basebackups(
            retention_count=1
        )

    assert deleted == 0
    # Row must still be there
    row = await fetch_one(
        "SELECT count(*)::int AS n FROM pitr_basebackups WHERE status = 'ok'"
    )
    assert row["n"] == 1
