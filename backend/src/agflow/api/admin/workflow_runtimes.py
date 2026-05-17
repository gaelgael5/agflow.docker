"""Endpoints workflow contracts v5 — runtimes.

- POST /api/admin/projects/{project_id}/runtimes
- GET  /api/admin/project-runtimes/{runtime_id}/resources
"""
from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator_or_m2m
from agflow.db.pool import fetch_one
from agflow.schemas.workflow import (
    ResourceState,
    RuntimeProvisionResponse,
    RuntimeResourcesResponse,
)
from agflow.services import workflow_provisioning_service as wp

_log = structlog.get_logger(__name__)

router = APIRouter(
    tags=["admin-workflow"],
    dependencies=[Depends(require_operator_or_m2m)],
)


def _map_status(db_status: str) -> str:
    """Map status DB (pending|deployed|failed) vers contrat v5 (provisioning|ready|failed)."""
    return {
        "pending": "provisioning",
        "deployed": "ready",
        "failed": "failed",
    }.get(db_status, db_status)


@router.post(
    "/api/admin/projects/{project_id}/runtimes",
    response_model=RuntimeProvisionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_runtime(project_id: UUID) -> RuntimeProvisionResponse:
    try:
        runtime_id = await wp.provision_runtime(project_id=project_id)
    except wp.ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "project_not_found", "message": str(exc)},
        ) from exc

    # Contrat v5 : retourne "provisioning" même si en DB c'est déjà 'deployed' (sync simulé).
    return RuntimeProvisionResponse(runtime_id=runtime_id, status="provisioning")


@router.get(
    "/api/admin/project-runtimes/{runtime_id}/resources",
    response_model=RuntimeResourcesResponse,
)
async def get_runtime_resources(runtime_id: UUID) -> RuntimeResourcesResponse:
    runtime = await fetch_one(
        "SELECT status FROM project_runtimes WHERE id = $1",
        runtime_id,
    )
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "runtime_not_found"},
        )

    rows = await wp.get_resources(runtime_id=runtime_id)
    resources = [
        ResourceState(
            instance_id=r["instance_id"],
            type=r["type"],
            name=r["name"],
            status=r["status"],
            connection_params=r.get("connection_params"),
        )
        for r in rows
    ]
    return RuntimeResourcesResponse(
        runtime_id=runtime_id,
        status=_map_status(runtime["status"]),
        resources=resources,
    )
