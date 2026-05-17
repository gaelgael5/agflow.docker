"""Endpoints workflow contracts v5 — sessions/agents/work/delete."""
from __future__ import annotations

import json
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from agflow.auth.dependencies import require_operator_or_m2m
from agflow.db.pool import execute, fetch_all, fetch_one, get_pool
from agflow.mom.envelope import Direction, Kind
from agflow.mom.publisher import MomPublisher
from agflow.schemas.workflow import (
    AgentCreateRequest,
    AgentCreateResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    WorkRequest,
    WorkResponse,
)
from agflow.services import (
    agents_instances_service,
    hmac_keys_service,
    sessions_service,
    tasks_service,
)

_log = structlog.get_logger(__name__)

_GROUPS_CONFIG = {
    Direction.IN: ["dispatcher"],
    Direction.OUT: ["ws_push", "router"],
}

router = APIRouter(
    tags=["admin-workflow"],
    dependencies=[Depends(require_operator_or_m2m)],
)


@router.post(
    "/api/admin/sessions",
    response_model=SessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_session(payload: SessionCreateRequest) -> SessionCreateResponse:
    if (
        payload.callback_hmac_key_id is not None
        and not await hmac_keys_service.exists(payload.callback_hmac_key_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "hmac_key_not_found"},
        )

    if payload.project_runtime_id is not None:
        runtime = await fetch_one(
            "SELECT id FROM project_runtimes WHERE id = $1",
            payload.project_runtime_id,
        )
        if runtime is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error": "runtime_not_found"},
            )

    session = await sessions_service.create(
        api_key_id=payload.api_key_id,
        name=payload.name,
        duration_seconds=payload.duration_seconds,
    )
    await execute(
        """
        UPDATE sessions
        SET project_runtime_id = $1,
            callback_url = $2,
            callback_hmac_key_id = $3
        WHERE id = $4
        """,
        payload.project_runtime_id,
        payload.callback_url,
        payload.callback_hmac_key_id,
        session["id"],
    )
    _log.info(
        "workflow.session.created",
        session_id=str(session["id"]),
        project_runtime_id=str(payload.project_runtime_id) if payload.project_runtime_id else None,
        has_callback=payload.callback_url is not None,
    )
    return SessionCreateResponse(
        session_id=session["id"],
        expires_at=session["expires_at"].isoformat(),
    )


@router.post(
    "/api/admin/sessions/{session_id}/agents",
    response_model=AgentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_agents(
    session_id: UUID, payload: AgentCreateRequest
) -> AgentCreateResponse:
    session_row = await fetch_one(
        "SELECT project_runtime_id FROM sessions WHERE id = $1",
        session_id,
    )
    if session_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "session_not_found"},
        )

    agent_ids = await agents_instances_service.create(
        session_id=session_id,
        agent_id=payload.agent_id,
        count=payload.count,
        labels=payload.labels,
        mission=payload.mission,
    )

    # Fusion MCP si session liée à runtime
    if session_row["project_runtime_id"] is not None:
        runtime_id = session_row["project_runtime_id"]
        instance_rows = await fetch_all(
            """
            SELECT i.mcp_bindings
            FROM instances i
            JOIN groups g ON g.id = i.group_id
            JOIN project_runtimes pr ON pr.project_id = g.project_id
            WHERE pr.id = $1
            """,
            runtime_id,
        )
        merged: list = []
        for r in instance_rows:
            mcp = r["mcp_bindings"]
            if isinstance(mcp, str):
                mcp = json.loads(mcp)
            if isinstance(mcp, list):
                merged.extend(mcp)

        for aid in agent_ids:
            await execute(
                "UPDATE agents_instances SET mcp_bindings_injected = $1::jsonb WHERE id = $2",
                json.dumps(merged),
                aid,
            )

    return AgentCreateResponse(agent_instance_ids=agent_ids)


@router.post(
    "/api/admin/sessions/{session_id}/agents/{agent_instance_id}/work",
    response_model=WorkResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_work(
    session_id: UUID,
    agent_instance_id: UUID,
    payload: WorkRequest,
) -> WorkResponse:
    task = await tasks_service.create_session_work(
        session_id=session_id,
        agent_instance_id=agent_instance_id,
        agflow_correlation_id=payload.agflow_correlation_id,
        instruction=payload.instruction,
    )
    if task["was_existing"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_correlation_id",
                "task_id": str(task["task_id"]),
            },
        )

    pool = await get_pool()
    publisher = MomPublisher(pool=pool, groups_config=_GROUPS_CONFIG)
    try:
        await publisher.publish(
            session_id=str(session_id),
            instance_id=str(agent_instance_id),
            direction=Direction.IN,
            source="m2m:workflow",
            kind=Kind.INSTRUCTION,
            payload={
                "instruction": payload.instruction,
                "_agflow_correlation_id": str(payload.agflow_correlation_id),
                "_agflow_task_id": str(task["task_id"]),
            },
        )
    except Exception as exc:
        _log.exception(
            "workflow.work.mom_publish_failed", task_id=str(task["task_id"])
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "mom_publish_failed", "message": str(exc)},
        ) from exc

    return WorkResponse(
        task_id=task["task_id"],
        agflow_correlation_id=payload.agflow_correlation_id,
    )


@router.delete(
    "/api/admin/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_session(
    session_id: UUID,
    force: bool = Query(default=False),
) -> None:
    if not force:
        row = await fetch_one(
            "SELECT status FROM sessions WHERE id = $1", session_id
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "session_not_found"},
            )
        if row["status"] != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "session_not_active"},
            )

    await sessions_service.close(
        session_id=session_id,
        api_key_id=session_id,  # ignoré quand is_admin=True
        is_admin=True,
    )
