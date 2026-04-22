"""Infrastructure named type actions — URLs par (named_type, action de catégorie).

Exemple : Proxmox/SSH + action platform/destroy → URL du script destroy-lxc.json.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.infra import NamedTypeActionRow

_log = structlog.get_logger(__name__)

_LIST_SQL = """
    SELECT
        a.id, a.named_type_id, a.category_action_id, a.url,
        a.created_at, a.updated_at,
        ca.name AS action_name
    FROM infra_named_type_actions a
    JOIN infra_category_actions ca ON ca.id = a.category_action_id
"""


class NamedTypeActionNotFoundError(Exception):
    pass


def _to_row(row: dict[str, Any]) -> NamedTypeActionRow:
    return NamedTypeActionRow(
        id=row["id"],
        named_type_id=row["named_type_id"],
        category_action_id=row["category_action_id"],
        action_name=row["action_name"],
        url=row["url"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_by_named_type(named_type_id: UUID) -> list[NamedTypeActionRow]:
    rows = await fetch_all(
        _LIST_SQL + " WHERE a.named_type_id = $1 ORDER BY ca.name",
        named_type_id,
    )
    return [_to_row(r) for r in rows]


async def get_by_id(action_id: UUID) -> NamedTypeActionRow:
    row = await fetch_one(_LIST_SQL + " WHERE a.id = $1", action_id)
    if row is None:
        raise NamedTypeActionNotFoundError(f"Action {action_id} not found")
    return _to_row(row)


async def create(
    named_type_id: UUID,
    category_action_id: UUID,
    url: str,
) -> NamedTypeActionRow:
    row = await fetch_one(
        """
        INSERT INTO infra_named_type_actions (named_type_id, category_action_id, url)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        named_type_id, category_action_id, url,
    )
    assert row is not None
    _log.info(
        "infra_named_type_actions.create",
        named_type_id=str(named_type_id),
        category_action_id=str(category_action_id),
    )
    return await get_by_id(row["id"])


async def update(action_id: UUID, url: str) -> NamedTypeActionRow:
    await get_by_id(action_id)
    await execute(
        "UPDATE infra_named_type_actions SET url = $1 WHERE id = $2",
        url, action_id,
    )
    _log.info("infra_named_type_actions.update", id=str(action_id))
    return await get_by_id(action_id)


async def delete(action_id: UUID) -> None:
    row = await fetch_one(
        "DELETE FROM infra_named_type_actions WHERE id = $1 RETURNING id", action_id,
    )
    if row is None:
        raise NamedTypeActionNotFoundError(f"Action {action_id} not found")
    _log.info("infra_named_type_actions.delete", id=str(action_id))
