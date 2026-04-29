from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import aiodocker
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from agflow.auth.dependencies import require_admin
from agflow.db.pool import fetch_all, fetch_one
from agflow.schemas.supervision import (
    AgentStatusCounts,
    InstanceDetail,
    MomDeliveryCounts,
    SessionStatusCounts,
    SupervisedInstance,
    SupervisionOverview,
)
from agflow.services import (
    agent_messages_service,
    agents_instances_service,
    container_runner,
)

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/admin/supervision", tags=["admin-supervision"])


def _labels_to_dict(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


@router.get("/overview", response_model=SupervisionOverview)
async def supervision_overview(
    _admin: str = Depends(require_admin),
) -> SupervisionOverview:
    sess_rows = await fetch_all("SELECT status, COUNT(*)::int AS n FROM sessions GROUP BY status")
    sess_map = {r["status"]: r["n"] for r in sess_rows}
    sessions = SessionStatusCounts(
        active=sess_map.get("active", 0),
        closed=sess_map.get("closed", 0),
        expired=sess_map.get("expired", 0),
    )

    alive_rows = await fetch_all(
        "SELECT status, COUNT(*)::int AS n "
        "FROM agents_instances WHERE destroyed_at IS NULL GROUP BY status"
    )
    alive_map = {r["status"]: r["n"] for r in alive_rows}
    destroyed_row = await fetch_one(
        "SELECT COUNT(*)::int AS n FROM agents_instances WHERE destroyed_at IS NOT NULL"
    )
    agents = AgentStatusCounts(
        idle=alive_map.get("idle", 0),
        busy=alive_map.get("busy", 0),
        error=alive_map.get("error", 0),
        destroyed_total=destroyed_row["n"] if destroyed_row else 0,
    )

    mom_rows = await fetch_all(
        "SELECT status, COUNT(*)::int AS n FROM agent_message_delivery GROUP BY status"
    )
    mom_map = {r["status"]: r["n"] for r in mom_rows}
    mom = MomDeliveryCounts(
        pending=mom_map.get("pending", 0),
        claimed=mom_map.get("claimed", 0),
        failed=mom_map.get("failed", 0),
    )

    containers_running: int | None
    try:
        running = await container_runner.list_running()
        containers_running = sum(1 for c in running if c.status == "running")
    except Exception as exc:
        _log.warning("supervision.list_running_failed", error=str(exc))
        containers_running = None

    return SupervisionOverview(
        sessions=sessions,
        agents=agents,
        containers_running=containers_running,
        mom=mom,
    )


@router.get("/instances", response_model=list[SupervisedInstance])
async def supervision_list_instances(
    _admin: str = Depends(require_admin),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[SupervisedInstance]:
    try:
        rows = await agents_instances_service.list_all_for_supervision(
            status=status_filter,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return [
        SupervisedInstance(
            id=r["id"],
            session_id=r["session_id"],
            agent_id=r["agent_id"],
            mission=r.get("mission"),
            status=r["status"],
            last_activity_at=r["last_activity_at"],
            created_at=r["created_at"],
            destroyed_at=r.get("destroyed_at"),
            error_message=r.get("error_message"),
            last_container_name=r.get("last_container_name"),
        )
        for r in rows
    ]


async def _inspect_container_status(container_name: str | None) -> str | None:
    if not container_name:
        return None
    try:
        docker = aiodocker.Docker()
        try:
            container = docker.containers.container(container_id=container_name)
            inspect = await container.show()
            state = inspect.get("State") or {}
            return state.get("Status")
        finally:
            await docker.close()
    except Exception as exc:
        _log.warning(
            "supervision.inspect_failed",
            container=container_name,
            error=str(exc),
        )
        return None


@router.get("/instances/{instance_id}", response_model=InstanceDetail)
async def supervision_get_instance(
    instance_id: UUID,
    _admin: str = Depends(require_admin),
) -> InstanceDetail:
    row = await fetch_one(
        """
        SELECT id, session_id, agent_id, labels, mission, created_at,
               destroyed_at, last_activity_at, status, error_message,
               last_container_name
        FROM agents_instances
        WHERE id = $1
        """,
        instance_id,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "instance not found")

    mom_rows = await fetch_all(
        """
        SELECT d.status, COUNT(*)::int AS n
        FROM agent_message_delivery d
        JOIN agent_messages m USING (msg_id)
        WHERE m.instance_id = $1
        GROUP BY d.status
        """,
        str(instance_id),
    )
    mom_map = {r["status"]: r["n"] for r in mom_rows}
    mom_counts = MomDeliveryCounts(
        pending=mom_map.get("pending", 0),
        claimed=mom_map.get("claimed", 0),
        failed=mom_map.get("failed", 0),
    )

    recent = await agent_messages_service.list_for_instance(
        session_id=row["session_id"],
        instance_id=instance_id,
        limit=10,
    )
    container_status = await _inspect_container_status(row["last_container_name"])

    return InstanceDetail(
        id=row["id"],
        session_id=row["session_id"],
        agent_id=row["agent_id"],
        labels=_labels_to_dict(row["labels"]),
        mission=row["mission"],
        status=row["status"],
        last_activity_at=row["last_activity_at"],
        created_at=row["created_at"],
        destroyed_at=row["destroyed_at"],
        error_message=row["error_message"],
        last_container_name=row["last_container_name"],
        container_status=container_status,
        mom_counts=mom_counts,
        recent_messages=recent,
    )
