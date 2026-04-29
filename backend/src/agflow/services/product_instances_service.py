"""Product instances service — asyncpg CRUD."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.products import InstanceSummary

_log = structlog.get_logger(__name__)


class InstanceNotFoundError(Exception):
    pass


def _to_summary(row: dict[str, Any]) -> InstanceSummary:
    variables = row.get("variables") or {}
    if isinstance(variables, str):
        variables = json.loads(variables)
    statuses = row.get("variable_statuses") or {}
    if isinstance(statuses, str):
        statuses = json.loads(statuses)
    return InstanceSummary(
        id=row["id"],
        group_id=row["group_id"],
        instance_name=row["instance_name"],
        catalog_id=row["catalog_id"],
        variables=variables,
        variable_statuses=statuses,
        status=row["status"],
        service_url=row.get("service_url"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_by_group(group_id: UUID) -> list[InstanceSummary]:
    rows = await fetch_all(
        "SELECT * FROM instances WHERE group_id = $1 ORDER BY instance_name",
        group_id,
    )
    return [_to_summary(r) for r in rows]


async def list_by_project(project_id: UUID) -> list[InstanceSummary]:
    rows = await fetch_all(
        """
        SELECT i.* FROM instances i
        JOIN groups g ON g.id = i.group_id
        WHERE g.project_id = $1
        ORDER BY i.instance_name
        """,
        project_id,
    )
    return [_to_summary(r) for r in rows]


async def list_all() -> list[InstanceSummary]:
    rows = await fetch_all("SELECT * FROM instances ORDER BY instance_name")
    return [_to_summary(r) for r in rows]


async def get_by_id(instance_id: UUID) -> InstanceSummary:
    row = await fetch_one("SELECT * FROM instances WHERE id = $1", instance_id)
    if row is None:
        raise InstanceNotFoundError(f"Instance {instance_id} not found")
    return _to_summary(row)


async def create(
    group_id: UUID,
    instance_name: str,
    catalog_id: str,
    variables: dict[str, str] | None = None,
    variable_statuses: dict[str, str] | None = None,
) -> InstanceSummary:
    row = await fetch_one(
        """
        INSERT INTO instances (group_id, instance_name, catalog_id, variables, variable_statuses)
        VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
        RETURNING *
        """,
        group_id, instance_name, catalog_id,
        json.dumps(variables or {}),
        json.dumps(variable_statuses or {}),
    )
    assert row is not None
    _log.info("instances.create", name=instance_name, group_id=str(group_id))
    return _to_summary(row)


async def update(instance_id: UUID, **kwargs: Any) -> InstanceSummary:
    await get_by_id(instance_id)
    updates: dict[str, Any] = {}
    jsonb_fields: set[str] = set()
    for field in ("instance_name", "service_url"):
        if field in kwargs and kwargs[field] is not None:
            updates[field] = kwargs[field]
    if "variables" in kwargs and kwargs["variables"] is not None:
        updates["variables"] = json.dumps(kwargs["variables"])
        jsonb_fields.add("variables")
    if "variable_statuses" in kwargs and kwargs["variable_statuses"] is not None:
        updates["variable_statuses"] = json.dumps(kwargs["variable_statuses"])
        jsonb_fields.add("variable_statuses")

    if not updates:
        return await get_by_id(instance_id)

    sets = []
    values = []
    for i, (k, v) in enumerate(updates.items(), 2):
        if k in jsonb_fields:
            sets.append(f"{k} = ${i}::jsonb")
        else:
            sets.append(f"{k} = ${i}")
        values.append(v)

    await execute(
        f"UPDATE instances SET {', '.join(sets)} WHERE id = $1",
        instance_id, *values,
    )
    _log.info("instances.update", id=str(instance_id))
    return await get_by_id(instance_id)


async def update_status(instance_id: UUID, status: str, service_url: str | None = None) -> InstanceSummary:
    if service_url is not None:
        await execute(
            "UPDATE instances SET status = $1, service_url = $2 WHERE id = $3",
            status, service_url, instance_id,
        )
    else:
        await execute(
            "UPDATE instances SET status = $1 WHERE id = $2",
            status, instance_id,
        )
    _log.info("instances.status_updated", id=str(instance_id), status=status)
    return await get_by_id(instance_id)


async def delete(instance_id: UUID) -> None:
    row = await fetch_one("DELETE FROM instances WHERE id = $1 RETURNING id", instance_id)
    if row is None:
        raise InstanceNotFoundError(f"Instance {instance_id} not found")
    _log.info("instances.delete", id=str(instance_id))
