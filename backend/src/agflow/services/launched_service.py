from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.launched import LaunchedTaskSummary

_log = structlog.get_logger(__name__)


class TaskNotFoundError(Exception):
    pass


async def create(
    dockerfile_id: str,
    instruction: str,
) -> LaunchedTaskSummary:
    row = await fetch_one(
        """
        INSERT INTO launched_tasks (dockerfile_id, instruction, status)
        VALUES ($1, $2, 'pending')
        RETURNING id, dockerfile_id, container_id, container_name, instruction,
                  status, started_at, finished_at, exit_code
        """,
        dockerfile_id,
        instruction,
    )
    assert row is not None
    _log.info("launched.create", task_id=str(row["id"]), dockerfile_id=dockerfile_id)
    return _to_summary(row)


async def set_running(task_id: UUID, container_id: str, container_name: str) -> None:
    await execute(
        """
        UPDATE launched_tasks
        SET status = 'running', container_id = $2, container_name = $3
        WHERE id = $1
        """,
        task_id,
        container_id,
        container_name,
    )


async def set_finished(task_id: UUID, status: str, exit_code: int | None = None) -> None:
    await execute(
        """
        UPDATE launched_tasks
        SET status = $2, exit_code = $3, finished_at = NOW()
        WHERE id = $1
        """,
        task_id,
        status,
        exit_code,
    )


async def list_all(dockerfile_id: str | None = None) -> list[LaunchedTaskSummary]:
    if dockerfile_id:
        rows = await fetch_all(
            """
            SELECT id, dockerfile_id, container_id, container_name, instruction,
                   status, started_at, finished_at, exit_code
            FROM launched_tasks
            WHERE dockerfile_id = $1
            ORDER BY started_at DESC
            """,
            dockerfile_id,
        )
    else:
        rows = await fetch_all(
            """
            SELECT id, dockerfile_id, container_id, container_name, instruction,
                   status, started_at, finished_at, exit_code
            FROM launched_tasks
            ORDER BY started_at DESC
            """
        )
    return [_to_summary(r) for r in rows]


async def get_by_id(task_id: UUID) -> dict[str, Any]:
    """Returns raw row (includes container_id for internal use)."""
    row = await fetch_one(
        """
        SELECT id, dockerfile_id, container_id, container_name, instruction,
               status, started_at, finished_at, exit_code
        FROM launched_tasks WHERE id = $1
        """,
        task_id,
    )
    if row is None:
        raise TaskNotFoundError(f"Task {task_id} not found")
    return dict(row)


async def stop(task_id: UUID) -> None:
    """Stop a running task. Caller must handle the actual Docker stop."""
    row = await get_by_id(task_id)
    if row["status"] not in ("pending", "running"):
        return
    await execute(
        """
        UPDATE launched_tasks
        SET status = 'stopped', finished_at = NOW()
        WHERE id = $1
        """,
        task_id,
    )
    _log.info("launched.stop", task_id=str(task_id))


def _to_summary(row: dict[str, Any]) -> LaunchedTaskSummary:
    return LaunchedTaskSummary(
        id=row["id"],
        dockerfile_id=row["dockerfile_id"],
        container_name=row.get("container_name"),
        instruction=row["instruction"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row.get("finished_at"),
        exit_code=row.get("exit_code"),
    )
