"""Provisioning workflow v5 — refacto tranche 2.

Changement vs T1 :
- `provision_runtime` crée le runtime (status='pending') + les rows
  project_runtime_instances (provisioning_status='provisioning') de manière
  atomique (transaction asyncpg). Le worker provisioning_worker reprend
  ensuite pour rendre Jinja et marquer status='ready'/'failed'.
- `get_resources` lit project_runtime_instances avec JOIN instances pour
  exposer les mcp_bindings du template + connection_params rendus du runtime.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import get_pool
from agflow.services import project_runtime_instances_service as pri_service

_log = structlog.get_logger(__name__)


class ProjectNotFoundError(Exception):
    pass


async def provision_runtime(*, project_id: UUID) -> UUID:
    """Crée un project_runtime (pending) + ses project_runtime_instances atomiquement.

    Le worker provisioning_worker reprendra ensuite pour rendre Jinja et
    marquer le runtime + ses instances comme ready/failed.

    Retourne le runtime_id.
    """
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        project = await conn.fetchrow(
            "SELECT id FROM projects WHERE id = $1", project_id
        )
        if project is None:
            raise ProjectNotFoundError(f"project {project_id} not found")

        # Liste les instances template du projet (via groups)
        instance_rows = await conn.fetch(
            """
            SELECT i.id
            FROM instances i
            JOIN groups g ON g.id = i.group_id
            WHERE g.project_id = $1
            ORDER BY i.created_at
            """,
            project_id,
        )
        instance_ids = [r["id"] for r in instance_rows]

        # INSERT runtime status='pending', user_id NULL = discriminant workflow m2m
        runtime_row = await conn.fetchrow(
            """
            INSERT INTO project_runtimes (project_id, status, user_id)
            VALUES ($1, 'pending', NULL)
            RETURNING id
            """,
            project_id,
        )
        assert runtime_row is not None
        runtime_id: UUID = runtime_row["id"]

        # Bulk INSERT des rows par instance avec status='provisioning'
        # (utilise la même connexion → atomic avec l'INSERT runtime)
        for instance_id in instance_ids:
            await conn.execute(
                """
                INSERT INTO project_runtime_instances
                (project_runtime_id, instance_id, provisioning_status)
                VALUES ($1, $2, 'provisioning')
                """,
                runtime_id,
                instance_id,
            )

    _log.info(
        "workflow.runtime.provisioned",
        runtime_id=str(runtime_id),
        project_id=str(project_id),
        instance_count=len(instance_ids),
    )
    return runtime_id


async def get_resources(*, runtime_id: UUID) -> list[dict[str, Any]]:
    """Liste les resources matérialisées d'un runtime au format contrat v5.

    Retourne :
    - resource_id (= project_runtime_instances.id)
    - type (= instances.catalog_id)
    - name (= instances.instance_name)
    - status (= project_runtime_instances.provisioning_status)
    - connection_params (rendus si status=ready)
    - mcp_bindings (du template, exposés à la volée via JOIN)
    - setup_steps (rendus si status=pending_setup)
    - error_message (si status=failed)
    """
    rows = await pri_service.list_by_runtime(project_runtime_id=runtime_id)
    return [
        {
            "resource_id": r["id"],
            "type": r["catalog_id"],
            "name": r["instance_name"],
            "status": r["provisioning_status"],
            "connection_params": r["connection_params"],
            "mcp_bindings": r["template_mcp_bindings"],
            "setup_steps": r["setup_steps"],
            "error_message": r["error_message"],
        }
        for r in rows
    ]
