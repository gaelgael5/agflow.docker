"""Projects service — asyncpg CRUD."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.products import ProjectSummary

_log = structlog.get_logger(__name__)


class ProjectNotFoundError(Exception):
    pass


def _to_summary(row: dict[str, Any]) -> ProjectSummary:
    tags = row.get("tags") or []
    if isinstance(tags, str):
        tags = json.loads(tags)
    return ProjectSummary(
        id=row["id"],
        display_name=row["display_name"],
        description=row["description"],
        environment=row["environment"],
        tags=tags,
        group_count=row.get("group_count", 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_all() -> list[ProjectSummary]:
    rows = await fetch_all(
        """
        SELECT p.*, coalesce(g.cnt, 0) AS group_count
        FROM projects p
        LEFT JOIN (SELECT project_id, count(*) AS cnt FROM groups GROUP BY project_id) g
            ON g.project_id = p.id
        ORDER BY p.display_name
        """
    )
    return [_to_summary(r) for r in rows]


async def get_by_id(project_id: UUID) -> ProjectSummary:
    row = await fetch_one(
        """
        SELECT p.*, coalesce(g.cnt, 0) AS group_count
        FROM projects p
        LEFT JOIN (SELECT project_id, count(*) AS cnt FROM groups GROUP BY project_id) g
            ON g.project_id = p.id
        WHERE p.id = $1
        """,
        project_id,
    )
    if row is None:
        raise ProjectNotFoundError(f"Project {project_id} not found")
    return _to_summary(row)


async def create(
    display_name: str,
    description: str = "",
    environment: str = "dev",
    tags: list[str] | None = None,
) -> ProjectSummary:
    row = await fetch_one(
        """
        INSERT INTO projects (display_name, description, environment, tags)
        VALUES ($1, $2, $3, $4::jsonb)
        RETURNING *, 0 AS group_count
        """,
        display_name, description, environment, json.dumps(tags or []),
    )
    assert row is not None
    _log.info("projects.create", name=display_name)
    return _to_summary(row)


async def update(project_id: UUID, **kwargs: Any) -> ProjectSummary:
    await get_by_id(project_id)
    updates: dict[str, Any] = {}
    for field in ("display_name", "description", "environment", "tags"):
        if field in kwargs and kwargs[field] is not None:
            val = kwargs[field]
            if field == "tags":
                val = json.dumps(val)
            updates[field] = val

    if not updates:
        return await get_by_id(project_id)

    sets = [f"{k} = ${i}" for i, k in enumerate(updates, 2)]
    await execute(
        f"UPDATE projects SET {', '.join(sets)} WHERE id = $1",
        project_id, *updates.values(),
    )
    _log.info("projects.update", id=str(project_id))
    return await get_by_id(project_id)


async def delete(project_id: UUID) -> None:
    row = await fetch_one("DELETE FROM projects WHERE id = $1 RETURNING id", project_id)
    if row is None:
        raise ProjectNotFoundError(f"Project {project_id} not found")
    _log.info("projects.delete", id=str(project_id))
