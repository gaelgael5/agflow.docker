"""GET endpoints for Swarm clusters (read-only)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.services import infra_swarm_clusters_service

router = APIRouter(
    prefix="/api/infra/swarm-clusters",
    tags=["infra-swarm-clusters"],
    dependencies=[Depends(require_admin)],
)


@router.get("", summary="List all Swarm clusters")
async def list_clusters() -> list[dict[str, Any]]:
    """Liste tous les clusters Swarm avec leur compte de nodes (manager/worker).

    Tokens JAMAIS retournes en clair.
    """
    return await infra_swarm_clusters_service.list_all()


@router.get("/{cluster_id}", summary="Get a Swarm cluster by id")
async def get_cluster(cluster_id: UUID) -> dict[str, Any]:
    cluster = await infra_swarm_clusters_service.get_by_id(cluster_id)
    if cluster is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")
    return cluster
