from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)

_VALID_STATUSES = ("idle", "busy", "error", "destroyed")


async def create(
    *,
    session_id: UUID,
    agent_id: str,
    count: int,
    labels: dict[str, Any],
    mission: str | None,
) -> list[UUID]:
    labels_json = json.dumps(labels, ensure_ascii=False)
    ids: list[UUID] = []
    for _ in range(count):
        row = await fetch_one(
            """
            INSERT INTO agents_instances (session_id, agent_id, labels, mission)
            VALUES ($1, $2, $3::jsonb, $4)
            RETURNING id
            """,
            session_id,
            agent_id,
            labels_json,
            mission,
        )
        ids.append(row["id"])
    _log.info(
        "agents_instances.created",
        session_id=str(session_id),
        agent_id=agent_id,
        count=count,
    )
    return ids


async def list_for_session(*, session_id: UUID) -> list[dict]:
    rows = await fetch_all(
        """
        SELECT id, session_id, agent_id, labels, mission,
               created_at, last_activity_at, status
        FROM agents_instances
        WHERE session_id = $1 AND destroyed_at IS NULL
        ORDER BY created_at
        """,
        session_id,
    )
    return [dict(r) for r in rows]


async def list_all_for_supervision(
    *,
    status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    if status is not None and status not in _VALID_STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    query = """
        SELECT id, session_id, agent_id, labels, mission,
               created_at, last_activity_at, status, error_message,
               destroyed_at, last_container_name
        FROM agents_instances
    """
    if status is None:
        query += " WHERE destroyed_at IS NULL"
    elif status == "destroyed":
        query += " WHERE destroyed_at IS NOT NULL"
    else:
        query += " WHERE destroyed_at IS NULL AND status = $1"
    query += " ORDER BY last_activity_at DESC LIMIT "
    # LIMIT doit être un littéral SQL, clampé
    query += str(max(1, min(1000, int(limit))))
    if status is None or status == "destroyed":
        rows = await fetch_all(query)
    else:
        rows = await fetch_all(query, status)
    return [dict(r) for r in rows]


async def get(*, session_id: UUID, instance_id: UUID) -> dict | None:
    row = await fetch_one(
        """
        SELECT id, session_id, agent_id, labels, mission,
               created_at, destroyed_at, last_activity_at,
               status, error_message, last_container_name
        FROM agents_instances
        WHERE id = $1 AND session_id = $2
        """,
        instance_id,
        session_id,
    )
    return dict(row) if row else None


async def destroy(*, session_id: UUID, instance_id: UUID) -> bool:
    result = await execute(
        """
        UPDATE agents_instances
        SET destroyed_at = now(), status = 'destroyed'
        WHERE id = $1 AND session_id = $2 AND destroyed_at IS NULL
        """,
        instance_id,
        session_id,
    )
    ok = result.endswith(" 1")
    if ok:
        _log.info(
            "agents_instances.destroyed",
            session_id=str(session_id),
            instance_id=str(instance_id),
        )
    return ok


async def touch_activity(
    *,
    instance_id: UUID,
    status: str | None = None,
    error_message: str | None = None,
) -> bool:
    """Met à jour last_activity_at et, optionnellement, status/error_message.

    Retourne True si une ligne non-destroyed a été modifiée.
    """
    if status is not None and status not in _VALID_STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    if status is None:
        result = await execute(
            """
            UPDATE agents_instances
            SET last_activity_at = now()
            WHERE id = $1 AND destroyed_at IS NULL
            """,
            instance_id,
        )
    else:
        result = await execute(
            """
            UPDATE agents_instances
            SET last_activity_at = now(),
                status = $2,
                error_message = $3
            WHERE id = $1 AND destroyed_at IS NULL
            """,
            instance_id,
            status,
            error_message,
        )
    return result.endswith(" 1")


async def set_last_container(
    *,
    instance_id: UUID,
    container_name: str | None,
) -> None:
    await execute(
        "UPDATE agents_instances SET last_container_name = $1 WHERE id = $2",
        container_name,
        instance_id,
    )


async def get_last_container_name(instance_id: UUID) -> str | None:
    row = await fetch_one(
        "SELECT last_container_name FROM agents_instances WHERE id = $1",
        instance_id,
    )
    return row["last_container_name"] if row else None
