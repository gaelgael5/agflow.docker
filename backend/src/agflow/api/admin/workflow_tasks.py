"""Endpoint GET /api/admin/tasks/{task_id} (status query workflow v5)."""
from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator_or_m2m
from agflow.schemas.workflow import TaskStatusResponse
from agflow.services import tasks_service

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/tasks",
    tags=["admin-workflow"],
    dependencies=[Depends(require_operator_or_m2m)],
)


@router.get(
    "/{task_id}",
    response_model=TaskStatusResponse,
)
async def get_task_status(task_id: UUID) -> TaskStatusResponse:
    task = await tasks_service.get_by_id(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "task_not_found"},
        )

    return TaskStatusResponse(
        task_id=task["task_id"],
        kind=task["kind"],
        status=task["status"],
        session_id=task.get("session_id"),
        agent_instance_id=task.get("agent_instance_id"),
        agflow_correlation_id=task.get("agflow_correlation_id"),
        agflow_action_execution_id=task.get("agflow_action_execution_id"),
        result=task.get("result"),
        error=task.get("error"),
        started_at=task["started_at"].isoformat() if task.get("started_at") else None,
        completed_at=task["completed_at"].isoformat() if task.get("completed_at") else None,
        created_at=task["created_at"].isoformat(),
    )
