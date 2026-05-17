"""CRUD de la table tasks (suivi des opérations workflow async)."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import structlog

from agflow.db.pool import fetch_one

_log = structlog.get_logger(__name__)


async def create_session_work(
    *,
    session_id: UUID,
    agent_instance_id: UUID,
    agflow_correlation_id: UUID,
    instruction: dict[str, Any],
) -> dict:
    """Crée une tâche kind='session_work' avec idempotence applicative.

    Si une tâche avec ce (session_id, agflow_correlation_id) existe déjà,
    on la retourne avec `was_existing=True` sans rien insérer (instruction
    ignorée).
    """
    existing = await fetch_one(
        """
        SELECT id, kind, status, agflow_correlation_id
        FROM tasks
        WHERE session_id = $1
          AND agflow_correlation_id = $2
          AND kind = 'session_work'
        """,
        session_id,
        agflow_correlation_id,
    )
    if existing:
        return {
            "task_id": existing["id"],
            "kind": existing["kind"],
            "status": existing["status"],
            "agflow_correlation_id": existing["agflow_correlation_id"],
            "was_existing": True,
        }

    row = await fetch_one(
        """
        INSERT INTO tasks (
            id, kind, session_id, agent_instance_id,
            agflow_correlation_id, status, result
        )
        VALUES ($1, 'session_work', $2, $3, $4, 'pending', $5::jsonb)
        RETURNING id, kind, status, agflow_correlation_id
        """,
        uuid4(),
        session_id,
        agent_instance_id,
        agflow_correlation_id,
        json.dumps({"instruction": instruction}),
    )
    assert row is not None  # INSERT RETURNING always returns a row
    _log.info(
        "workflow.task.created",
        task_id=str(row["id"]),
        session_id=str(session_id),
        agent_instance_id=str(agent_instance_id),
        agflow_correlation_id=str(agflow_correlation_id),
    )
    return {
        "task_id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "agflow_correlation_id": row["agflow_correlation_id"],
        "was_existing": False,
    }


async def get_by_id(task_id: UUID) -> dict | None:
    row = await fetch_one(
        """
        SELECT id, kind, status, session_id, agent_instance_id,
               agflow_correlation_id, result, error,
               created_at, completed_at
        FROM tasks
        WHERE id = $1
        """,
        task_id,
    )
    if row is None:
        return None
    return {
        "task_id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "session_id": row["session_id"],
        "agent_instance_id": row["agent_instance_id"],
        "agflow_correlation_id": row["agflow_correlation_id"],
        "result": row["result"],
        "error": row["error"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }
