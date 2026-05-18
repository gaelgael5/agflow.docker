"""Construction du body JSON du hook task-completed v5.

Conforme docs/contracts/hook-docker-task-completed.md §4.4 (JSON Schema).
Tous les UUIDs sont serialisés en string. Dates en ISO-8601 UTC.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID


def build_task_completed_payload(
    *,
    hook_id: UUID,
    task_id: UUID,
    action_execution_id: UUID,
    correlation_id: UUID,
    project_runtime_id: UUID | None,
    session_id: UUID,
    agent_uuid: UUID,
    agent_slug: str,
    container_id: str | None,
    status: str,  # 'completed' | 'failed' | 'cancelled'
    started_at: datetime,
    completed_at: datetime,
    result: dict[str, Any] | None,
    error: dict[str, Any] | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Retourne le dict JSON-serializable conforme §4.4 du contrat v5."""
    return {
        "hook_id": str(hook_id),
        "task_id": str(task_id),
        "action_execution_id": str(action_execution_id),
        "correlation_id": str(correlation_id),
        "project_runtime_id": str(project_runtime_id) if project_runtime_id else None,
        "session_id": str(session_id),
        "agent_uuid": str(agent_uuid),
        "container_id": container_id or "",
        "agent_slug": agent_slug,
        "status": status,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "result": result,
        "error": error,
        "metadata": metadata,
    }
