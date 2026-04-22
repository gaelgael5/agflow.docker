"""Infrastructure machines runs — historique d'exécution des actions.

Chaque run = une invocation de script (via une action named_type) sur une machine.
Capture started_at, finished_at, success, exit_code, error_message.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.infra import MachineRunRow

_log = structlog.get_logger(__name__)

_LIST_SQL = """
    SELECT
        r.id, r.machine_id, r.action_id,
        r.started_at, r.finished_at, r.success, r.exit_code, r.error_message,
        ca.name AS action_name
    FROM infra_machines_runs r
    JOIN infra_named_type_actions a ON a.id = r.action_id
    JOIN infra_category_actions ca ON ca.id = a.category_action_id
"""


class MachineRunNotFoundError(Exception):
    pass


def _to_row(row: dict[str, Any]) -> MachineRunRow:
    return MachineRunRow(
        id=row["id"],
        machine_id=row["machine_id"],
        action_id=row["action_id"],
        action_name=row["action_name"],
        started_at=row["started_at"],
        finished_at=row.get("finished_at"),
        success=row.get("success"),
        exit_code=row.get("exit_code"),
        error_message=row.get("error_message"),
    )


async def list_by_machine(machine_id: UUID, limit: int = 50) -> list[MachineRunRow]:
    rows = await fetch_all(
        _LIST_SQL + " WHERE r.machine_id = $1 ORDER BY r.started_at DESC LIMIT $2",
        machine_id, limit,
    )
    return [_to_row(r) for r in rows]


async def get_by_id(run_id: UUID) -> MachineRunRow:
    row = await fetch_one(_LIST_SQL + " WHERE r.id = $1", run_id)
    if row is None:
        raise MachineRunNotFoundError(f"Run {run_id} not found")
    return _to_row(row)


async def start(machine_id: UUID, action_id: UUID) -> MachineRunRow:
    """Record the start of a script run. Returns the created row."""
    row = await fetch_one(
        """
        INSERT INTO infra_machines_runs (machine_id, action_id)
        VALUES ($1, $2)
        RETURNING id
        """,
        machine_id, action_id,
    )
    assert row is not None
    _log.info(
        "infra_machines_runs.start",
        machine_id=str(machine_id),
        action_id=str(action_id),
        run_id=str(row["id"]),
    )
    return await get_by_id(row["id"])


async def finish(
    run_id: UUID,
    success: bool,
    exit_code: int | None = None,
    error_message: str | None = None,
) -> MachineRunRow:
    """Mark a run as finished with its outcome."""
    await execute(
        """
        UPDATE infra_machines_runs
        SET finished_at = now(), success = $1, exit_code = $2, error_message = $3
        WHERE id = $4
        """,
        success, exit_code, error_message, run_id,
    )
    _log.info(
        "infra_machines_runs.finish",
        run_id=str(run_id),
        success=success,
        exit_code=exit_code,
    )
    return await get_by_id(run_id)
