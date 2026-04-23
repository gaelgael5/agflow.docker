"""project_runtimes + project_group_runtimes — matérialisation d'un déploiement."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.runtimes import (
    ProjectGroupRuntimeDetail,
    ProjectGroupRuntimeRow,
    ProjectRuntimeRow,
)

_log = structlog.get_logger(__name__)


class ProjectRuntimeNotFoundError(Exception):
    pass


class ProjectGroupRuntimeNotFoundError(Exception):
    pass


def _to_group_runtime(row: dict[str, Any], detail: bool = False) -> ProjectGroupRuntimeRow:
    common = dict(
        id=row["id"],
        seq=row.get("seq", 0),
        project_runtime_id=row["project_runtime_id"],
        group_id=row["group_id"],
        group_name=row.get("group_name", ""),
        machine_id=row.get("machine_id"),
        machine_name=row.get("machine_name", "") or row.get("machine_host", "") or "",
        remote_path=row.get("remote_path", ""),
        status=row.get("status", "pending"),
        pushed_at=row.get("pushed_at"),
        error_message=row.get("error_message"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
    if detail:
        return ProjectGroupRuntimeDetail(
            **common,
            env_text=row.get("env_text", "") or "",
            compose_yaml=row.get("compose_yaml", "") or "",
        )
    return ProjectGroupRuntimeRow(**common)


_GROUP_RUNTIME_SELECT = """
    SELECT
        gr.id, gr.seq, gr.project_runtime_id, gr.group_id, gr.machine_id,
        gr.remote_path, gr.status, gr.pushed_at, gr.error_message,
        gr.created_at, gr.updated_at,
        g.name AS group_name,
        m.name AS machine_name, m.host AS machine_host
    FROM project_group_runtimes gr
    JOIN groups g ON g.id = gr.group_id
    LEFT JOIN infra_machines m ON m.id = gr.machine_id
"""

_GROUP_RUNTIME_DETAIL_SELECT = """
    SELECT
        gr.id, gr.seq, gr.project_runtime_id, gr.group_id, gr.machine_id,
        gr.env_text, gr.compose_yaml, gr.remote_path, gr.status,
        gr.pushed_at, gr.error_message, gr.created_at, gr.updated_at,
        g.name AS group_name,
        m.name AS machine_name, m.host AS machine_host
    FROM project_group_runtimes gr
    JOIN groups g ON g.id = gr.group_id
    LEFT JOIN infra_machines m ON m.id = gr.machine_id
"""


async def list_group_runtimes_by_group(group_id: UUID) -> list[ProjectGroupRuntimeRow]:
    rows = await fetch_all(
        _GROUP_RUNTIME_SELECT
        + " WHERE gr.group_id = $1 AND gr.deleted_at IS NULL ORDER BY gr.seq DESC",
        group_id,
    )
    return [_to_group_runtime(r) for r in rows]


async def get_group_runtime(runtime_id: UUID) -> ProjectGroupRuntimeDetail:
    row = await fetch_one(
        _GROUP_RUNTIME_DETAIL_SELECT + " WHERE gr.id = $1 AND gr.deleted_at IS NULL",
        runtime_id,
    )
    if row is None:
        raise ProjectGroupRuntimeNotFoundError(f"project_group_runtime {runtime_id} not found")
    return _to_group_runtime(row, detail=True)  # type: ignore[return-value]


async def soft_delete_group_runtime(runtime_id: UUID) -> None:
    await execute(
        "UPDATE project_group_runtimes SET deleted_at = now() WHERE id = $1",
        runtime_id,
    )


async def upsert_project_runtime(
    project_id: UUID, deployment_id: UUID, user_id: UUID | None,
) -> tuple[UUID, int]:
    """Create a new project_runtime for this deployment (one per push).

    Returns (runtime_id, seq).
    """
    row = await fetch_one(
        """
        INSERT INTO project_runtimes (project_id, deployment_id, user_id)
        VALUES ($1, $2, $3)
        RETURNING id, seq
        """,
        project_id, deployment_id, user_id,
    )
    assert row is not None
    return row["id"], row["seq"]


async def upsert_group_runtime(
    project_runtime_id: UUID,
    group_id: UUID,
    machine_id: UUID | None,
) -> UUID:
    """Create a group_runtime entry for this runtime×group pair."""
    row = await fetch_one(
        """
        INSERT INTO project_group_runtimes (project_runtime_id, group_id, machine_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (project_runtime_id, group_id) DO UPDATE
            SET machine_id = EXCLUDED.machine_id
        RETURNING id
        """,
        project_runtime_id, group_id, machine_id,
    )
    assert row is not None
    return row["id"]


async def update_group_runtime_push(
    runtime_id: UUID,
    env_text: str,
    compose_yaml: str,
    remote_path: str,
    status: str,
    error_message: str | None = None,
) -> None:
    await execute(
        """
        UPDATE project_group_runtimes
        SET env_text = $2, compose_yaml = $3, remote_path = $4,
            status = $5::varchar, error_message = $6,
            pushed_at = CASE WHEN $5::varchar = 'deployed' THEN now() ELSE pushed_at END
        WHERE id = $1
        """,
        runtime_id, env_text, compose_yaml, remote_path, status, error_message,
    )


async def update_project_runtime_status(
    runtime_id: UUID, status: str, error_message: str | None = None,
) -> None:
    await execute(
        """
        UPDATE project_runtimes
        SET status = $2::varchar, error_message = $3,
            pushed_at = CASE WHEN $2::varchar = 'deployed' THEN now() ELSE pushed_at END
        WHERE id = $1
        """,
        runtime_id, status, error_message,
    )


async def list_runtimes_by_project(project_id: UUID) -> list[ProjectRuntimeRow]:
    rows = await fetch_all(
        """
        SELECT
            pr.id, pr.seq, pr.project_id, pr.deployment_id, pr.user_id,
            pr.status, pr.pushed_at, pr.error_message,
            pr.created_at, pr.updated_at,
            u.email AS user_email
        FROM project_runtimes pr
        LEFT JOIN users u ON u.id = pr.user_id
        WHERE pr.project_id = $1 AND pr.deleted_at IS NULL
        ORDER BY pr.seq DESC
        """,
        project_id,
    )
    result: list[ProjectRuntimeRow] = []
    for r in rows:
        groups = await fetch_all(
            _GROUP_RUNTIME_SELECT
            + " WHERE gr.project_runtime_id = $1 AND gr.deleted_at IS NULL ORDER BY g.name",
            r["id"],
        )
        result.append(
            ProjectRuntimeRow(
                id=r["id"],
                seq=r.get("seq", 0),
                project_id=r["project_id"],
                deployment_id=r.get("deployment_id"),
                user_id=r.get("user_id"),
                user_email=r.get("user_email"),
                status=r.get("status", "pending"),
                pushed_at=r.get("pushed_at"),
                error_message=r.get("error_message"),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                group_runtimes=[_to_group_runtime(g) for g in groups],
            )
        )
    return result
