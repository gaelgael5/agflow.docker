"""Tests pour pitr_clone_service."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from agflow.db.pool import fetch_one
from agflow.services import pitr_clone_service
from agflow.services.pitr_clone_service import NoActiveCloneError
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


async def _seed_clone(*, status: str, expires_at: datetime) -> UUID:
    base = datetime.now(UTC).replace(microsecond=0)
    bb = await fetch_one(
        "INSERT INTO pitr_basebackups (pgbackrest_label, started_at, completed_at, "
        "status, recovery_window_start, recovery_window_end) "
        "VALUES ('20260520-030000F', $1, $1, 'ok', $1, $2) RETURNING id",
        base - timedelta(days=2), base,
    )
    clone = await fetch_one(
        "INSERT INTO pitr_clones (basebackup_id, target_time, status, expires_at, "
        "postgres_container_name, pgweb_container_name, pgweb_port) "
        "VALUES ($1, $2, $3, $4, 'agflow-pitr-clone-abcd1234', 'agflow-pitr-pgweb-abcd1234', 32768) "
        "RETURNING id",
        bb["id"], base - timedelta(hours=1), status, expires_at,
    )
    return clone["id"]


def _make_fake_docker() -> AsyncMock:
    docker = AsyncMock()
    container = AsyncMock()
    container.stop = AsyncMock()
    container.delete = AsyncMock()
    docker.containers.get = AsyncMock(return_value=container)
    docker.volumes.get = AsyncMock(return_value=AsyncMock(delete=AsyncMock()))
    docker.networks.get = AsyncMock(return_value=AsyncMock(delete=AsyncMock()))
    docker.close = AsyncMock()
    return docker


async def test_get_active_clone_returns_none_when_no_clone() -> None:
    await reset_schema_and_migrate()
    assert await pitr_clone_service.get_active_clone() is None


async def test_get_active_clone_returns_ready_clone() -> None:
    await reset_schema_and_migrate()
    now = datetime.now(UTC).replace(microsecond=0)
    cid = await _seed_clone(status="ready", expires_at=now + timedelta(hours=23))
    active = await pitr_clone_service.get_active_clone()
    assert active is not None
    assert active.id == cid
    assert active.status == "ready"
    assert active.pgweb_url == "http://192.168.10.158:32768"


async def test_extend_active_clone_adds_24h() -> None:
    await reset_schema_and_migrate()
    now = datetime.now(UTC).replace(microsecond=0)
    expires_before = now + timedelta(hours=1)
    cid = await _seed_clone(status="ready", expires_at=expires_before)
    refreshed = await pitr_clone_service.extend_active_clone()
    assert refreshed.id == cid
    # New expires should be >= expires_before + 23h (allow small drift)
    new_expires_row = await fetch_one(
        "SELECT expires_at FROM pitr_clones WHERE id = $1", cid
    )
    assert new_expires_row["expires_at"] >= expires_before + timedelta(hours=23, minutes=59)


async def test_extend_active_clone_raises_when_no_clone() -> None:
    await reset_schema_and_migrate()
    with pytest.raises(NoActiveCloneError):
        await pitr_clone_service.extend_active_clone()


async def test_terminate_active_clone_marks_terminated_and_cleans_artifacts() -> None:
    await reset_schema_and_migrate()
    now = datetime.now(UTC).replace(microsecond=0)
    cid = await _seed_clone(status="ready", expires_at=now + timedelta(hours=23))
    docker = _make_fake_docker()
    with patch("agflow.services.pitr_clone_service._aiodocker", return_value=docker):
        await pitr_clone_service.terminate_active_clone()
    row = await fetch_one(
        "SELECT status, terminated_at FROM pitr_clones WHERE id = $1", cid
    )
    assert row["status"] == "terminated"
    assert row["terminated_at"] is not None
    # Verify docker artifacts were cleaned
    assert docker.containers.get.call_count == 2  # pgweb + postgres
    assert docker.volumes.get.call_count == 1
    assert docker.networks.get.call_count == 1


async def test_terminate_active_clone_raises_when_no_clone() -> None:
    await reset_schema_and_migrate()
    with pytest.raises(NoActiveCloneError):
        await pitr_clone_service.terminate_active_clone()


async def test_cleanup_expired_clones_terminates_expired_ready_clone() -> None:
    await reset_schema_and_migrate()
    now = datetime.now(UTC).replace(microsecond=0)
    cid = await _seed_clone(status="ready", expires_at=now - timedelta(minutes=10))
    docker = _make_fake_docker()
    with patch("agflow.services.pitr_clone_service._aiodocker", return_value=docker):
        n = await pitr_clone_service.cleanup_expired_clones()
    assert n == 1
    row = await fetch_one("SELECT status FROM pitr_clones WHERE id = $1", cid)
    assert row["status"] == "terminated"


async def test_cleanup_expired_clones_returns_zero_when_no_expired() -> None:
    await reset_schema_and_migrate()
    now = datetime.now(UTC).replace(microsecond=0)
    await _seed_clone(status="ready", expires_at=now + timedelta(hours=23))
    n = await pitr_clone_service.cleanup_expired_clones()
    assert n == 0
