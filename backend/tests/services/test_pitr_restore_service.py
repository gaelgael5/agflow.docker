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


# ---------------------------------------------------------------------------
# T13 — _provision_clone
# ---------------------------------------------------------------------------


class _FakeStream:
    """Minimal async context manager that yields no messages (drain ends immediately)."""

    async def __aenter__(self) -> _FakeStream:
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    async def read_out(self) -> None:
        return None


class _FakeExec:
    def __init__(self, exit_code: int) -> None:
        self._code = exit_code

    def start(self, *, detach: bool) -> _FakeStream:
        return _FakeStream()

    async def inspect(self) -> dict:
        return {"ExitCode": self._code}


def _make_fake_container(
    *,
    exec_exit: int = 0,
    container_id: str = "cid",
    port: str = "32768",
) -> AsyncMock:
    """Build a minimal fake aiodocker Container supporting _provision_clone methods."""
    container = AsyncMock()
    container.id = container_id
    container.exec = AsyncMock(return_value=_FakeExec(exec_exit))
    container.start = AsyncMock()
    container.show = AsyncMock(
        return_value={
            "NetworkSettings": {"Ports": {"8081/tcp": [{"HostPort": port}]}}
        }
    )
    container.stop = AsyncMock()
    container.delete = AsyncMock()
    return container


def _make_fake_docker(*, pg_exit_code: int = 0, pgweb_port: str = "32768") -> AsyncMock:
    """Build a fake aiodocker Docker client."""
    docker = AsyncMock()
    pg_container = _make_fake_container(exec_exit=pg_exit_code, container_id="pg-id")
    pgweb_container = _make_fake_container(container_id="pgweb-id", port=pgweb_port)

    docker.networks.create = AsyncMock(return_value=AsyncMock())
    docker.volumes.create = AsyncMock(return_value=AsyncMock())
    docker.containers.create_or_replace = AsyncMock(
        side_effect=[pg_container, pgweb_container]
    )

    # For cleanup path:
    docker.containers.get = AsyncMock(side_effect=[pgweb_container, pg_container])
    docker.volumes.get = AsyncMock(return_value=AsyncMock(delete=AsyncMock()))
    docker.networks.get = AsyncMock(return_value=AsyncMock(delete=AsyncMock()))
    docker.close = AsyncMock()
    return docker


async def test_provision_clone_happy_path_marks_ready() -> None:
    await reset_schema_and_migrate()
    base = datetime.now(UTC).replace(microsecond=0)
    bb_id = await _seed_basebackup_with_window(
        "bb-1", base - timedelta(days=2), base - timedelta(hours=1)
    )
    target = base - timedelta(minutes=30)
    clone_row = await fetch_one(
        "INSERT INTO pitr_clones (basebackup_id, target_time, status, expires_at) "
        "VALUES ($1, $2, 'restoring', $3) RETURNING id",
        bb_id, target, base + timedelta(hours=24),
    )
    assert clone_row is not None
    cid = clone_row["id"]

    fake_docker = _make_fake_docker(pg_exit_code=0, pgweb_port="32768")
    with patch(
        "agflow.services.pitr_restore_service._aiodocker",
        return_value=fake_docker,
    ):
        await pitr_restore_service._provision_clone(cid)

    row = await fetch_one(
        "SELECT status, pgweb_port, postgres_container_name, pgweb_container_name "
        "FROM pitr_clones WHERE id = $1",
        cid,
    )
    assert row is not None
    assert row["status"] == "ready"
    assert row["pgweb_port"] == 32768
    assert row["postgres_container_name"].startswith("agflow-pitr-clone-")
    assert row["pgweb_container_name"].startswith("agflow-pitr-pgweb-")


async def test_provision_clone_port_discovery_retries_on_empty_ports():
    """If pgweb's NetworkSettings.Ports is empty on first show(), retry succeeds."""
    await reset_schema_and_migrate()
    base = datetime.now(UTC).replace(microsecond=0)
    bb_id = await _seed_basebackup_with_window(
        "bb-1", base - timedelta(days=2), base - timedelta(hours=1)
    )
    clone_row = await fetch_one(
        "INSERT INTO pitr_clones (basebackup_id, target_time, status, expires_at) "
        "VALUES ($1, $2, 'restoring', $3) RETURNING id",
        bb_id, base - timedelta(minutes=30), base + timedelta(hours=24),
    )
    cid = clone_row["id"]

    # Build a fake docker where pgweb.show() returns empty Ports on the 1st & 2nd calls,
    # then populated on the 3rd. Verifies the retry loop works.
    pg_container = _make_fake_container(exec_exit=0, container_id="pg-id")
    pgweb_container = _make_fake_container(container_id="pgweb-id", port="32768")

    # Override show() with a side_effect list: 2 empty responses, then populated
    pgweb_container.show = AsyncMock(side_effect=[
        {"NetworkSettings": {"Ports": {}}},
        {"NetworkSettings": {"Ports": {"8081/tcp": []}}},
        {"NetworkSettings": {"Ports": {"8081/tcp": [{"HostPort": "32768"}]}}},
    ])

    docker = AsyncMock()
    docker.networks.create = AsyncMock(return_value=AsyncMock())
    docker.volumes.create = AsyncMock(return_value=AsyncMock())
    docker.containers.create_or_replace = AsyncMock(side_effect=[pg_container, pgweb_container])
    docker.containers.get = AsyncMock(side_effect=[pgweb_container, pg_container])
    docker.volumes.get = AsyncMock(return_value=AsyncMock(delete=AsyncMock()))
    docker.networks.get = AsyncMock(return_value=AsyncMock(delete=AsyncMock()))
    docker.close = AsyncMock()

    with patch(
        "agflow.services.pitr_restore_service._aiodocker",
        return_value=docker,
    ), patch(
        "agflow.services.pitr_restore_service.asyncio.sleep",
        new=AsyncMock(),
    ):
        await pitr_restore_service._provision_clone(cid)

    row = await fetch_one("SELECT status, pgweb_port FROM pitr_clones WHERE id = $1", cid)
    assert row["status"] == "ready"
    assert row["pgweb_port"] == 32768
    assert pgweb_container.show.call_count == 3


async def test_provision_clone_marks_failed_on_pg_not_ready() -> None:
    await reset_schema_and_migrate()
    base = datetime.now(UTC).replace(microsecond=0)
    bb_id = await _seed_basebackup_with_window(
        "bb-1", base - timedelta(days=2), base - timedelta(hours=1)
    )
    clone_row = await fetch_one(
        "INSERT INTO pitr_clones (basebackup_id, target_time, status, expires_at) "
        "VALUES ($1, $2, 'restoring', $3) RETURNING id",
        bb_id, base - timedelta(minutes=30), base + timedelta(hours=24),
    )
    assert clone_row is not None
    cid = clone_row["id"]

    fake_docker = _make_fake_docker(pg_exit_code=1)  # pg_isready always fails
    # Speed up the healthcheck loop — don't actually wait 5 min
    with patch(
        "agflow.services.pitr_restore_service._aiodocker",
        return_value=fake_docker,
    ), patch(
        "agflow.services.pitr_restore_service.HEALTHCHECK_TIMEOUT_S",
        new=1,
    ), patch(
        "agflow.services.pitr_restore_service.asyncio.sleep",
        new=AsyncMock(),
    ):
        await pitr_restore_service._provision_clone(cid)

    row = await fetch_one(
        "SELECT status, error FROM pitr_clones WHERE id = $1", cid
    )
    assert row is not None
    assert row["status"] == "failed"
    assert "ready" in (row["error"] or "").lower()
    # Cleanup must have been invoked
    fake_docker.networks.get.assert_called()
    fake_docker.volumes.get.assert_called()
