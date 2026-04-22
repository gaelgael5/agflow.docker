"""group_scripts — liaison script ↔ groupe avec contexte d'exécution."""
from __future__ import annotations

import json as _json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.scripts import GroupScriptRow

_log = structlog.get_logger(__name__)

_LIST_SQL = """
    SELECT
        gs.id, gs.group_id, gs.script_id, gs.machine_id, gs.timing, gs.position,
        gs.env_mapping, gs.created_at, gs.updated_at,
        s.name AS script_name,
        m.name AS machine_name_raw, m.host AS machine_host
    FROM group_scripts gs
    JOIN scripts s ON s.id = gs.script_id
    JOIN infra_machines m ON m.id = gs.machine_id
"""


class GroupScriptNotFoundError(Exception):
    pass


def _to_row(row: dict[str, Any]) -> GroupScriptRow:
    mapping = row.get("env_mapping") or {}
    if isinstance(mapping, str):
        mapping = _json.loads(mapping)
    machine_name = row.get("machine_name_raw") or row.get("machine_host") or ""
    return GroupScriptRow(
        id=row["id"],
        group_id=row["group_id"],
        script_id=row["script_id"],
        script_name=row["script_name"],
        machine_id=row["machine_id"],
        machine_name=machine_name,
        timing=row["timing"],
        position=row["position"],
        env_mapping=mapping,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_by_group(group_id: UUID) -> list[GroupScriptRow]:
    rows = await fetch_all(
        _LIST_SQL + " WHERE gs.group_id = $1 ORDER BY gs.timing, gs.position, s.name",
        group_id,
    )
    return [_to_row(r) for r in rows]


async def get_by_id(link_id: UUID) -> GroupScriptRow:
    row = await fetch_one(_LIST_SQL + " WHERE gs.id = $1", link_id)
    if row is None:
        raise GroupScriptNotFoundError(f"group_script {link_id} not found")
    return _to_row(row)


async def create(
    group_id: UUID,
    script_id: UUID,
    machine_id: UUID,
    timing: str,
    position: int = 0,
    env_mapping: dict[str, str] | None = None,
) -> GroupScriptRow:
    row = await fetch_one(
        """
        INSERT INTO group_scripts (group_id, script_id, machine_id, timing, position, env_mapping)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        RETURNING id
        """,
        group_id, script_id, machine_id, timing, position, _json.dumps(env_mapping or {}),
    )
    assert row is not None
    _log.info("group_scripts.create", group_id=str(group_id), script_id=str(script_id))
    return await get_by_id(row["id"])


async def update(link_id: UUID, **kwargs: Any) -> GroupScriptRow:
    await get_by_id(link_id)

    updates: dict[str, Any] = {}
    for field in ("script_id", "machine_id", "timing", "position"):
        if field in kwargs and kwargs[field] is not None:
            updates[field] = kwargs[field]
    if "env_mapping" in kwargs and kwargs["env_mapping"] is not None:
        updates["env_mapping"] = _json.dumps(kwargs["env_mapping"])

    if not updates:
        return await get_by_id(link_id)

    sets = []
    values = []
    for i, (k, v) in enumerate(updates.items(), 2):
        if k == "env_mapping":
            sets.append(f"{k} = ${i}::jsonb")
        else:
            sets.append(f"{k} = ${i}")
        values.append(v)

    await execute(
        f"UPDATE group_scripts SET {', '.join(sets)} WHERE id = $1",
        link_id, *values,
    )
    _log.info("group_scripts.update", id=str(link_id))
    return await get_by_id(link_id)


async def delete(link_id: UUID) -> None:
    result = await execute("DELETE FROM group_scripts WHERE id = $1", link_id)
    if result.endswith(" 0"):
        raise GroupScriptNotFoundError(f"group_script {link_id} not found")
    _log.info("group_scripts.delete", id=str(link_id))
