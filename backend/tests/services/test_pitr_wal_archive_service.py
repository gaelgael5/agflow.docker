"""Tests pour pitr_wal_archive_service."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agflow.db.pool import execute, fetch_one
from agflow.services import pitr_wal_archive_service
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


PG_INFO_SAMPLE = json.dumps([{
    "name": "agflow",
    "archive": [{
        "id": "16-1",
        "min": "000000010000000000000001",
        "max": "000000010000000000000010",
    }],
    "backup": [{"label": "20260520-030000F", "info": {"size": 1000}}],
    "status": {"code": 0},
}])


DF_SAMPLE_OUTPUT = (
    "Filesystem     1B-blocks         Used  Available Use% Mounted on\n"
    "/dev/sda1   50000000000  4200000000 45000000000   9% /var/lib/pgbackrest\n"
)


async def test_get_wal_status_returns_archive_disk_and_archiving_state():
    await reset_schema_and_migrate()
    mock_exec = AsyncMock()
    # Order: pgbackrest info, stat (for last archive timestamp), df
    mock_exec.side_effect = [
        (0, PG_INFO_SAMPLE, ""),       # info
        (0, "1716207000\n", ""),       # stat last WAL mtime (epoch seconds)
        (0, DF_SAMPLE_OUTPUT, ""),     # df
    ]
    with patch(
        "agflow.services.pitr_wal_archive_service._pg_exec", mock_exec
    ), patch(
        "agflow.services.pitr_wal_archive_service._archive_mode_on",
        new=AsyncMock(return_value=True),
    ):
        status = await pitr_wal_archive_service.get_wal_status()

    assert status.archiving_enabled is True
    assert status.wal_disk_used_bytes == 4_200_000_000
    assert status.wal_disk_free_bytes == 45_000_000_000
    assert status.last_archived_at is not None


async def test_get_wal_status_handles_unparseable_info():
    """If pgbackrest info returns malformed JSON, return safe defaults but still report archiving."""
    await reset_schema_and_migrate()
    mock_exec = AsyncMock()
    mock_exec.side_effect = [
        (1, "stanza not initialized", ""),  # info fails
        (0, DF_SAMPLE_OUTPUT, ""),          # df still works
    ]
    with patch(
        "agflow.services.pitr_wal_archive_service._pg_exec", mock_exec
    ), patch(
        "agflow.services.pitr_wal_archive_service._archive_mode_on",
        new=AsyncMock(return_value=False),
    ):
        status = await pitr_wal_archive_service.get_wal_status()

    assert status.archiving_enabled is False
    assert status.last_archived_at is None
    assert status.archive_lag_seconds is None
    assert status.wal_disk_used_bytes == 4_200_000_000


async def test_refresh_recovery_windows_updates_ok_rows():
    """Updates recovery_window_end on every status='ok' row. Returns count."""
    await reset_schema_and_migrate()
    # Seed 2 OK rows + 1 running (should not be touched)
    await execute(
        "INSERT INTO pitr_basebackups (pgbackrest_label, started_at, completed_at, status) "
        "VALUES ('20260518-030000F', now() - interval '2 day', now() - interval '2 day', 'ok')"
    )
    await execute(
        "INSERT INTO pitr_basebackups (pgbackrest_label, started_at, completed_at, status) "
        "VALUES ('20260519-030000F', now() - interval '1 day', now() - interval '1 day', 'ok')"
    )
    await execute(
        "INSERT INTO pitr_basebackups (pgbackrest_label, started_at, status) "
        "VALUES ('20260520-running', now(), 'running')"
    )

    mock_exec = AsyncMock(return_value=(0, PG_INFO_SAMPLE, ""))
    with patch("agflow.services.pitr_wal_archive_service._pg_exec", mock_exec):
        n = await pitr_wal_archive_service.refresh_recovery_windows()

    assert n == 2  # only the 2 'ok' rows updated

    # Verify the running row was NOT touched
    running_row = await fetch_one(
        "SELECT recovery_window_end FROM pitr_basebackups WHERE pgbackrest_label = '20260520-running'"
    )
    assert running_row["recovery_window_end"] is None
