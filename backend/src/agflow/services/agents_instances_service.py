from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)


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
            session_id, agent_id, labels_json, mission,
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
        SELECT
            i.id,
            i.session_id,
            i.agent_id,
            i.labels,
            i.mission,
            i.created_at,
            CASE WHEN EXISTS (
                SELECT 1
                FROM agent_messages m
                JOIN agent_message_delivery d
                  ON d.msg_id = m.msg_id AND d.group_name = 'dispatcher'
                WHERE m.instance_id = i.id::text
                  AND m.direction = 'in'
                  AND m.kind = 'instruction'
                  AND d.status IN ('pending','claimed')
            ) THEN 'busy' ELSE 'idle' END AS status
        FROM agents_instances i
        WHERE i.session_id = $1 AND i.destroyed_at IS NULL
        ORDER BY i.created_at
        """,
        session_id,
    )
    return [dict(r) for r in rows]


async def get(*, session_id: UUID, instance_id: UUID) -> dict | None:
    row = await fetch_one(
        """
        SELECT id, session_id, agent_id, labels, mission, created_at, destroyed_at
        FROM agents_instances
        WHERE id = $1 AND session_id = $2
        """,
        instance_id, session_id,
    )
    return dict(row) if row else None


async def destroy(*, session_id: UUID, instance_id: UUID) -> bool:
    result = await execute(
        """
        UPDATE agents_instances
        SET destroyed_at = now()
        WHERE id = $1 AND session_id = $2 AND destroyed_at IS NULL
        """,
        instance_id, session_id,
    )
    ok = result.endswith(" 1")
    if ok:
        _log.info(
            "agents_instances.destroyed",
            session_id=str(session_id),
            instance_id=str(instance_id),
        )
    return ok
