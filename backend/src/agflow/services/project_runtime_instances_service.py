"""CRUD de project_runtime_instances (matérialisation resources par runtime).

Symétrique à project_runtimes_service / project_group_runtimes mais à la
granularité instance individuelle. Le `id` de cette table = `resource_id`
exposé via le contrat workflow v5 §3.4.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)


async def create_bulk(
    *,
    project_runtime_id: UUID,
    instance_ids: list[UUID],
) -> list[dict]:
    """Insère 1 row par instance_id avec status='provisioning'."""
    if not instance_ids:
        return []

    # asyncpg ne supporte pas executemany RETURNING — on boucle.
    created: list[dict] = []
    for instance_id in instance_ids:
        row = await fetch_one(
            """
            INSERT INTO project_runtime_instances
            (project_runtime_id, instance_id, provisioning_status)
            VALUES ($1, $2, 'provisioning')
            RETURNING id, project_runtime_id, instance_id, provisioning_status
            """,
            project_runtime_id,
            instance_id,
        )
        assert row is not None
        created.append(
            {
                "id": row["id"],
                "project_runtime_id": row["project_runtime_id"],
                "instance_id": row["instance_id"],
                "provisioning_status": row["provisioning_status"],
            }
        )

    _log.info(
        "workflow.runtime_instances.created_bulk",
        runtime_id=str(project_runtime_id),
        count=len(created),
    )
    return created


async def list_by_runtime(*, project_runtime_id: UUID) -> list[dict]:
    """Liste toutes les rows pour un runtime, JOIN instances pour catalog_id+mcp_bindings."""
    rows = await fetch_all(
        """
        SELECT
            pri.id, pri.project_runtime_id, pri.instance_id,
            pri.connection_params, pri.setup_steps, pri.provisioning_status,
            pri.container_id, pri.service_url, pri.error_message,
            pri.created_at, pri.updated_at,
            i.instance_name, i.catalog_id, i.mcp_bindings AS template_mcp_bindings
        FROM project_runtime_instances pri
        JOIN instances i ON i.id = pri.instance_id
        WHERE pri.project_runtime_id = $1
        ORDER BY pri.created_at
        """,
        project_runtime_id,
    )
    return [dict(r) for r in rows]


async def get_by_id(pri_id: UUID) -> dict | None:
    row = await fetch_one(
        """
        SELECT
            pri.id, pri.project_runtime_id, pri.instance_id,
            pri.connection_params, pri.setup_steps, pri.provisioning_status,
            pri.container_id, pri.service_url, pri.error_message,
            i.instance_name, i.catalog_id, i.mcp_bindings AS template_mcp_bindings
        FROM project_runtime_instances pri
        JOIN instances i ON i.id = pri.instance_id
        WHERE pri.id = $1
        """,
        pri_id,
    )
    return dict(row) if row else None


async def mark_status(
    *,
    pri_id: UUID,
    status: str,
    connection_params: dict[str, Any] | None = None,
    setup_steps: list[dict[str, Any]] | None = None,
    container_id: str | None = None,
    service_url: str | None = None,
) -> None:
    """Marque le statut + écrit les champs rendus. status ∈ {ready, pending_setup}."""
    await execute(
        """
        UPDATE project_runtime_instances
        SET provisioning_status = $1,
            connection_params = COALESCE($2::jsonb, connection_params),
            setup_steps = COALESCE($3::jsonb, setup_steps),
            container_id = COALESCE($4, container_id),
            service_url = COALESCE($5, service_url),
            error_message = NULL
        WHERE id = $6
        """,
        status,
        json.dumps(connection_params) if connection_params is not None else None,
        json.dumps(setup_steps) if setup_steps is not None else None,
        container_id,
        service_url,
        pri_id,
    )
    _log.info("workflow.runtime_instance.status_set", pri_id=str(pri_id), status=status)


async def mark_failed(*, pri_id: UUID, error_message: str) -> None:
    await execute(
        """
        UPDATE project_runtime_instances
        SET provisioning_status = 'failed',
            error_message = $1
        WHERE id = $2
        """,
        error_message,
        pri_id,
    )
    _log.warning(
        "workflow.runtime_instance.failed",
        pri_id=str(pri_id),
        error=error_message,
    )
