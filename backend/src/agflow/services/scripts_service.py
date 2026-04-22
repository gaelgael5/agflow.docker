"""Scripts service — shell scripts stored as TEXT in DB (see migration 070)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.scripts import ScriptRow, ScriptSummary

_log = structlog.get_logger(__name__)

_FULL_SELECT = """
    s.id, s.name, s.description, s.content, s.execute_on_types_named,
    s.created_at, s.updated_at,
    nt.name AS execute_on_types_named_name
"""
_SUMMARY_SELECT = """
    s.id, s.name, s.description, s.execute_on_types_named,
    s.created_at, s.updated_at,
    nt.name AS execute_on_types_named_name
"""
_FROM_JOIN = "FROM scripts s LEFT JOIN infra_named_types nt ON nt.id = s.execute_on_types_named"


class ScriptNotFoundError(Exception):
    pass


def _to_row(row: dict[str, Any]) -> ScriptRow:
    return ScriptRow(
        id=row["id"],
        name=row["name"],
        description=row.get("description", ""),
        content=row.get("content", ""),
        execute_on_types_named=row.get("execute_on_types_named"),
        execute_on_types_named_name=row.get("execute_on_types_named_name"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_summary(row: dict[str, Any]) -> ScriptSummary:
    return ScriptSummary(
        id=row["id"],
        name=row["name"],
        description=row.get("description", ""),
        execute_on_types_named=row.get("execute_on_types_named"),
        execute_on_types_named_name=row.get("execute_on_types_named_name"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_all() -> list[ScriptSummary]:
    rows = await fetch_all(f"SELECT {_SUMMARY_SELECT} {_FROM_JOIN} ORDER BY s.name")
    return [_to_summary(r) for r in rows]


async def get_by_id(script_id: UUID) -> ScriptRow:
    row = await fetch_one(f"SELECT {_FULL_SELECT} {_FROM_JOIN} WHERE s.id = $1", script_id)
    if row is None:
        raise ScriptNotFoundError(f"Script {script_id} not found")
    return _to_row(row)


async def create(
    name: str,
    description: str = "",
    content: str = "",
    execute_on_types_named: UUID | None = None,
) -> ScriptRow:
    row = await fetch_one(
        """
        INSERT INTO scripts (name, description, content, execute_on_types_named)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        name, description, content, execute_on_types_named,
    )
    assert row is not None
    _log.info("scripts.create", name=name)
    return await get_by_id(row["id"])


async def update(script_id: UUID, **kwargs: Any) -> ScriptRow:
    await get_by_id(script_id)

    updates: dict[str, Any] = {}
    for field in ("name", "description", "content", "execute_on_types_named"):
        if field in kwargs:
            updates[field] = kwargs[field]

    if not updates:
        return await get_by_id(script_id)

    sets = [f"{k} = ${i}" for i, k in enumerate(updates, 2)]
    await fetch_one(
        f"UPDATE scripts SET {', '.join(sets)} WHERE id = $1 RETURNING id",
        script_id, *updates.values(),
    )
    _log.info("scripts.update", id=str(script_id))
    return await get_by_id(script_id)


async def delete(script_id: UUID) -> None:
    result = await execute("DELETE FROM scripts WHERE id = $1", script_id)
    if result.endswith(" 0"):
        raise ScriptNotFoundError(f"Script {script_id} not found")
    _log.info("scripts.delete", id=str(script_id))
