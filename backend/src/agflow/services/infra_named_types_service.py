"""Infrastructure named types — variantes typées (ex. Proxmox/SSH, LXC/SSH).

Remplace les fichiers JSON `backend/data/platforms/*.json` et
`backend/data/services/*.json` (supprimés lors de la migration 064).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.infra import NamedTypeRow

_log = structlog.get_logger(__name__)

_LIST_SQL = """
    SELECT
        nt.id, nt.name, nt.type_id, nt.sub_type_id, nt.connection_type,
        nt.created_at, nt.updated_at,
        nt.type_id AS type_name,
        sub.name AS sub_type_name
    FROM infra_named_types nt
    LEFT JOIN infra_named_types sub ON sub.id = nt.sub_type_id
"""


class NamedTypeNotFoundError(Exception):
    pass


def _to_row(row: dict[str, Any]) -> NamedTypeRow:
    return NamedTypeRow(
        id=row["id"],
        name=row.get("name", ""),
        type_id=row["type_id"],
        type_name=row["type_name"],
        sub_type_id=row.get("sub_type_id"),
        sub_type_name=row.get("sub_type_name"),
        connection_type=row["connection_type"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_all() -> list[NamedTypeRow]:
    rows = await fetch_all(_LIST_SQL + " ORDER BY nt.name")
    return [_to_row(r) for r in rows]


async def get_by_id(named_type_id: UUID) -> NamedTypeRow:
    row = await fetch_one(_LIST_SQL + " WHERE nt.id = $1", named_type_id)
    if row is None:
        raise NamedTypeNotFoundError(f"NamedType {named_type_id} not found")
    return _to_row(row)


async def create(
    name: str,
    type_id: str,
    connection_type: str,
    sub_type_id: UUID | None = None,
) -> NamedTypeRow:
    row = await fetch_one(
        """
        INSERT INTO infra_named_types (name, type_id, sub_type_id, connection_type)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        name, type_id, sub_type_id, connection_type,
    )
    assert row is not None
    _log.info("infra_named_types.create", name=name, type_id=type_id)
    return await get_by_id(row["id"])


async def update(named_type_id: UUID, **kwargs: Any) -> NamedTypeRow:
    await get_by_id(named_type_id)

    updates: dict[str, Any] = {}
    for field in ("name", "type_id", "sub_type_id", "connection_type"):
        if field in kwargs:
            updates[field] = kwargs[field]

    if not updates:
        return await get_by_id(named_type_id)

    sets = [f"{k} = ${i}" for i, k in enumerate(updates, 2)]
    await execute(
        f"UPDATE infra_named_types SET {', '.join(sets)} WHERE id = $1",
        named_type_id, *updates.values(),
    )
    _log.info("infra_named_types.update", id=str(named_type_id))
    return await get_by_id(named_type_id)


async def delete(named_type_id: UUID) -> None:
    row = await fetch_one(
        "DELETE FROM infra_named_types WHERE id = $1 RETURNING id", named_type_id,
    )
    if row is None:
        raise NamedTypeNotFoundError(f"NamedType {named_type_id} not found")
    _log.info("infra_named_types.delete", id=str(named_type_id))
