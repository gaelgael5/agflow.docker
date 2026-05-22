"""Tests pour local_backup_pushes_service."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agflow.db.pool import execute, fetch_one
from agflow.services import local_backup_pushes_service
from agflow.services.local_backup_pushes_service import (
    LocalFileMissingError,
    PushNotFoundError,
)
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


async def _seed_backup_and_remote() -> tuple:
    await reset_schema_and_migrate()
    bb = await fetch_one(
        "INSERT INTO local_backups (filename, file_path, size_bytes, status) "
        "VALUES ('t.dump', '/tmp/t.dump', 1024, 'ok') RETURNING id"
    )
    rm = await fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('r', 'sftp', '{}'::jsonb) RETURNING id"
    )
    return bb["id"], rm["id"]


async def test_seed_pushes_inserts_one_row_per_remote():
    bid, rid = await _seed_backup_and_remote()
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])
    row = await fetch_one(
        "SELECT status FROM local_backup_pushes WHERE local_backup_id=$1 AND remote_connection_id=$2",
        bid, rid,
    )
    assert row["status"] == "pending"


async def test_seed_pushes_idempotent_on_conflict():
    bid, rid = await _seed_backup_and_remote()
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])
    count = await fetch_one(
        "SELECT count(*)::int AS n FROM local_backup_pushes WHERE local_backup_id=$1", bid
    )
    assert count["n"] == 1


async def test_list_pushes_with_remote_name():
    bid, rid = await _seed_backup_and_remote()
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])
    pushes = await local_backup_pushes_service.list_pushes(bid)
    assert len(pushes) == 1
    assert pushes[0].remote_connection_name == "r"
    assert pushes[0].status == "pending"


async def test_push_all_pending_happy_marks_ok():
    bid, rid = await _seed_backup_and_remote()
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])

    fake_provider = AsyncMock()
    fake_provider.upload_stream = AsyncMock(return_value=1024)

    with patch(
        "agflow.services.local_backup_pushes_service._provider_for",
        new=AsyncMock(return_value=(fake_provider, "/opt/backups")),
    ):
        all_ok = await local_backup_pushes_service.push_all_pending(backup_id=bid)
    assert all_ok is True
    row = await fetch_one(
        "SELECT status, remote_path, size_bytes FROM local_backup_pushes WHERE local_backup_id=$1",
        bid,
    )
    assert row["status"] == "ok"
    assert row["size_bytes"] == 1024


async def test_push_all_pending_partial_fail_returns_false():
    bid, rid = await _seed_backup_and_remote()
    rm2 = await fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('r2', 'sftp', '{}'::jsonb) RETURNING id"
    )
    await local_backup_pushes_service.seed_pushes(
        backup_id=bid, remote_ids=[rid, rm2["id"]]
    )

    providers = [
        AsyncMock(upload_stream=AsyncMock(return_value=1024)),
        AsyncMock(upload_stream=AsyncMock(side_effect=RuntimeError("net down"))),
    ]
    call_count = {"i": 0}

    async def _fake_provider_for(*args, **kwargs):
        p = providers[call_count["i"]]
        call_count["i"] += 1
        return p, "/opt/backups"

    with patch(
        "agflow.services.local_backup_pushes_service._provider_for",
        side_effect=_fake_provider_for,
    ):
        all_ok = await local_backup_pushes_service.push_all_pending(backup_id=bid)

    assert all_ok is False
    rows = await fetch_one(
        "SELECT count(*) FILTER (WHERE status='ok') AS ok_n, "
        "count(*) FILTER (WHERE status='failed') AS fail_n "
        "FROM local_backup_pushes WHERE local_backup_id=$1",
        bid,
    )
    assert rows["ok_n"] == 1
    assert rows["fail_n"] == 1


async def test_push_one_idempotent_when_already_ok():
    bid, rid = await _seed_backup_and_remote()
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])
    await execute(
        "UPDATE local_backup_pushes SET status='ok' WHERE local_backup_id=$1", bid
    )

    fake_provider = AsyncMock()
    with patch(
        "agflow.services.local_backup_pushes_service._provider_for",
        new=AsyncMock(return_value=(fake_provider, "/opt/backups")),
    ):
        await local_backup_pushes_service.push_one(backup_id=bid, remote_id=rid)
    fake_provider.upload_stream.assert_not_called()


async def test_push_one_404_when_push_not_found():
    await reset_schema_and_migrate()
    with pytest.raises(PushNotFoundError):
        await local_backup_pushes_service.push_one(
            backup_id=uuid4(), remote_id=uuid4()
        )


async def test_push_one_409_when_local_file_missing():
    bid, rid = await _seed_backup_and_remote()
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])
    await execute(
        "UPDATE local_backups SET local_file_present=false WHERE id=$1", bid
    )
    with pytest.raises(LocalFileMissingError):
        await local_backup_pushes_service.push_one(backup_id=bid, remote_id=rid)
