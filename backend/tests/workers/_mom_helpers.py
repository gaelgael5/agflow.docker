"""Helpers MOM partagés pour les tests workers (module interne, non collecté par pytest)."""
from __future__ import annotations

import json
from uuid import UUID

from asyncpg import Connection


async def publish_mom_result(
    fresh_db: Connection,
    *,
    session_id: UUID,
    instance_id: UUID,
    task_id: UUID,
    payload: dict,
    kind: str = "result",
) -> None:
    """Insère manuellement un message agent_messages OUT + agent_message_delivery
    pour simuler la publication par un agent.
    """
    msg_id = await fresh_db.fetchval(
        """
        INSERT INTO agent_messages
        (session_id, instance_id, direction, kind, payload, source)
        VALUES ($1::text, $2::text, 'out', $3, $4::jsonb, 'test')
        RETURNING msg_id
        """,
        str(session_id),
        str(instance_id),
        kind,
        json.dumps(payload),
    )
    await fresh_db.execute(
        "INSERT INTO agent_message_delivery (group_name, msg_id, status) "
        "VALUES ('workflow_task_completed', $1, 'pending')",
        msg_id,
    )
