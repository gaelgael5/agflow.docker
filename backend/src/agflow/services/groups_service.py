"""Groups service — asyncpg CRUD."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.products import GroupSummary

_log = structlog.get_logger(__name__)


class GroupNotFoundError(Exception):
    pass


def _to_summary(row: dict[str, Any]) -> GroupSummary:
    return GroupSummary(
        id=row["id"],
        project_id=row["project_id"],
        name=row["name"],
        max_agents=row["max_agents"],
        instance_count=row.get("instance_count", 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_LIST_SQL = """
    SELECT g.*, coalesce(i.cnt, 0) AS instance_count
    FROM groups g
    LEFT JOIN (SELECT group_id, count(*) AS cnt FROM instances GROUP BY group_id) i
        ON i.group_id = g.id
"""


async def list_by_project(project_id: UUID) -> list[GroupSummary]:
    rows = await fetch_all(
        _LIST_SQL + " WHERE g.project_id = $1 ORDER BY g.name",
        project_id,
    )
    return [_to_summary(r) for r in rows]


async def get_by_id(group_id: UUID) -> GroupSummary:
    row = await fetch_one(
        _LIST_SQL + " WHERE g.id = $1",
        group_id,
    )
    if row is None:
        raise GroupNotFoundError(f"Group {group_id} not found")
    return _to_summary(row)


async def create(
    project_id: UUID,
    name: str,
    max_agents: int = 0,
) -> GroupSummary:
    row = await fetch_one(
        """
        INSERT INTO groups (project_id, name, max_agents)
        VALUES ($1, $2, $3)
        RETURNING *, 0 AS instance_count
        """,
        project_id, name, max_agents,
    )
    assert row is not None
    _log.info("groups.create", name=name, project_id=str(project_id))
    return _to_summary(row)


async def update(group_id: UUID, **kwargs: Any) -> GroupSummary:
    await get_by_id(group_id)
    updates: dict[str, Any] = {}
    for field in ("name", "max_agents"):
        if field in kwargs and kwargs[field] is not None:
            updates[field] = kwargs[field]

    if not updates:
        return await get_by_id(group_id)

    sets = [f"{k} = ${i}" for i, k in enumerate(updates, 2)]
    await execute(
        f"UPDATE groups SET {', '.join(sets)} WHERE id = $1",
        group_id, *updates.values(),
    )
    _log.info("groups.update", id=str(group_id))
    return await get_by_id(group_id)


async def delete(group_id: UUID) -> None:
    row = await fetch_one("DELETE FROM groups WHERE id = $1 RETURNING id", group_id)
    if row is None:
        raise GroupNotFoundError(f"Group {group_id} not found")
    _log.info("groups.delete", id=str(group_id))
