"""Provisioning d'un project_runtime selon le contrat workflow v5.

Tranche 1 : sync simulé. INSERT project_runtimes + UPDATE status='deployed'
immédiatement. Pas de worker, pas de templating Jinja des connection_params.
"""
from __future__ import annotations

from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)


class ProjectNotFoundError(Exception):
    pass


async def provision_runtime(*, project_id: UUID) -> UUID:
    """Crée un project_runtime et marque status='deployed' (sync simulé).

    Retourne le runtime_id.
    """
    project = await fetch_one("SELECT id FROM projects WHERE id = $1", project_id)
    if project is None:
        raise ProjectNotFoundError(f"project {project_id} not found")

    row = await fetch_one(
        """
        INSERT INTO project_runtimes (project_id, status, user_id)
        VALUES ($1, 'pending', NULL)
        RETURNING id
        """,
        project_id,
    )
    runtime_id: UUID = row["id"]

    # Tranche 1 : sync simulé — pas de worker, status passe immédiatement à deployed.
    await execute(
        "UPDATE project_runtimes SET status = 'deployed' WHERE id = $1",
        runtime_id,
    )

    _log.info(
        "workflow.runtime.provisioned",
        runtime_id=str(runtime_id),
        project_id=str(project_id),
    )
    return runtime_id


async def get_resources(*, runtime_id: UUID) -> list[dict]:
    """Liste les resources (instances) du runtime via le projet.

    Tranche 1 : on récupère les instances du projet (toutes groups confondues).
    En tranche 2, chaque resource sera dupliquée par runtime.
    """
    runtime = await fetch_one(
        "SELECT project_id FROM project_runtimes WHERE id = $1",
        runtime_id,
    )
    if runtime is None:
        return []

    rows = await fetch_all(
        """
        SELECT i.id AS instance_id, i.catalog_id AS type,
               i.instance_name AS name, i.provisioning_status AS status,
               i.connection_params
        FROM instances i
        JOIN groups g ON g.id = i.group_id
        WHERE g.project_id = $1
        ORDER BY i.created_at
        """,
        runtime["project_id"],
    )
    return [dict(r) for r in rows]
