"""Tests pour pitr_restore_service — get_restore_window + start_clone (T12).

_provision_clone is patched out in start_clone tests; its real implementation comes in T13.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from agflow.db.pool import execute, fetch_one
from agflow.services import pitr_restore_service
from agflow.services.pitr_restore_service import (
    CloneAlreadyActiveError,
    InvalidTargetTimeError,
    RestoreWindowEmptyError,
)
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


async def _seed_basebackup_with_window(
    label: str,
    start: datetime,
    end: datetime,
) -> UUID:
    row = await fetch_one(
        "INSERT INTO pitr_basebackups (pgbackrest_label, started_at, completed_at, "
        "status, recovery_window_start, recovery_window_end) "
        "VALUES ($1, $2, $2, 'ok', $2, $3) RETURNING id",
        label, start, end,
    )
    return row["id"]


async def test_get_restore_window_raises_when_empty():
    await reset_schema_and_migrate()
    with pytest.raises(RestoreWindowEmptyError):
        await pitr_restore_service.get_restore_window()


async def test_get_restore_window_returns_aggregated_bounds():
    await reset_schema_and_migrate()
    base = datetime.now(UTC).replace(microsecond=0)
    earliest = base - timedelta(days=7)
    middle = base - timedelta(days=3)
    latest = base - timedelta(hours=1)
    await _seed_basebackup_with_window("bb-old", earliest, middle)
    await _seed_basebackup_with_window("bb-recent", middle, latest)

    win = await pitr_restore_service.get_restore_window()
    assert win.earliest == earliest
    assert win.latest == latest


async def test_start_clone_raises_when_target_out_of_window():
    await reset_schema_and_migrate()
    base = datetime.now(UTC).replace(microsecond=0)
    await _seed_basebackup_with_window(
        "bb-1", base - timedelta(days=7), base - timedelta(hours=1)
    )
    far_future = base + timedelta(days=10)
    with pytest.raises(InvalidTargetTimeError):
        await pitr_restore_service.start_clone(far_future, actor_user_id=None)


async def test_start_clone_raises_when_clone_already_active():
    await reset_schema_and_migrate()
    base = datetime.now(UTC).replace(microsecond=0)
    bb_id = await _seed_basebackup_with_window(
        "bb-1", base - timedelta(days=2), base - timedelta(hours=1)
    )
    # Seed an active clone
    await execute(
        "INSERT INTO pitr_clones (basebackup_id, target_time, status, expires_at) "
        "VALUES ($1, $2, 'ready', $3)",
        bb_id, base - timedelta(hours=2), base + timedelta(hours=22),
    )
    with pytest.raises(CloneAlreadyActiveError):
        await pitr_restore_service.start_clone(
            base - timedelta(hours=1), actor_user_id=None
        )


async def test_start_clone_inserts_restoring_row_and_returns_id():
    await reset_schema_and_migrate()
    base = datetime.now(UTC).replace(microsecond=0)
    await _seed_basebackup_with_window(
        "bb-1", base - timedelta(days=2), base - timedelta(hours=1)
    )
    target = base - timedelta(minutes=30)

    # Patch out the background provisioning (T13 work)
    with patch(
        "agflow.services.pitr_restore_service._provision_clone",
        new=AsyncMock(),
    ):
        clone_id = await pitr_restore_service.start_clone(target, actor_user_id=None)

    assert isinstance(clone_id, UUID)
    row = await fetch_one(
        "SELECT status, target_time, basebackup_id FROM pitr_clones WHERE id = $1",
        clone_id,
    )
    assert row["status"] == "restoring"
    assert row["target_time"] == target


async def test_start_clone_picks_oldest_basebackup_covering_target():
    """If 2 basebackups cover the target, prefer the oldest (smallest restore time)."""
    await reset_schema_and_migrate()
    base = datetime.now(UTC).replace(microsecond=0)
    # Both basebackups have recovery_window_end >= target
    older_id = await _seed_basebackup_with_window(
        "bb-older", base - timedelta(days=5), base
    )
    await _seed_basebackup_with_window(
        "bb-newer", base - timedelta(days=2), base
    )

    target = base - timedelta(hours=1)
    with patch(
        "agflow.services.pitr_restore_service._provision_clone",
        new=AsyncMock(),
    ):
        clone_id = await pitr_restore_service.start_clone(target, actor_user_id=None)

    row = await fetch_one(
        "SELECT basebackup_id FROM pitr_clones WHERE id = $1", clone_id
    )
    assert row["basebackup_id"] == older_id
