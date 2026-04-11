from __future__ import annotations

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.service_types import ServiceTypeSummary

_log = structlog.get_logger(__name__)

_COLS = "name, display_name, is_native, position, created_at"


class ServiceTypeNotFoundError(Exception):
    pass


class DuplicateServiceTypeError(Exception):
    pass


class ProtectedServiceTypeError(Exception):
    """Raised when attempting to delete a native (system) service type."""


class ServiceTypeInUseError(Exception):
    """Raised when deleting a type that is still referenced by a role."""


def _row(row: dict) -> ServiceTypeSummary:
    return ServiceTypeSummary(**row)


async def list_all() -> list[ServiceTypeSummary]:
    rows = await fetch_all(
        f"SELECT {_COLS} FROM service_types ORDER BY position ASC, name ASC"
    )
    return [_row(r) for r in rows]


async def get(name: str) -> ServiceTypeSummary:
    row = await fetch_one(
        f"SELECT {_COLS} FROM service_types WHERE name = $1", name
    )
    if row is None:
        raise ServiceTypeNotFoundError(f"Service type '{name}' not found")
    return _row(row)


async def create(name: str, display_name: str) -> ServiceTypeSummary:
    existing = await list_all()
    next_position = max((s.position for s in existing), default=-1) + 1
    try:
        row = await fetch_one(
            f"""
            INSERT INTO service_types (name, display_name, is_native, position)
            VALUES ($1, $2, FALSE, $3)
            RETURNING {_COLS}
            """,
            name,
            display_name,
            next_position,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateServiceTypeError(
            f"Service type '{name}' already exists"
        ) from exc
    assert row is not None
    _log.info("service_types.create", name=name)
    return _row(row)


async def delete(name: str) -> None:
    existing = await get(name)
    if existing.is_native:
        raise ProtectedServiceTypeError(
            f"Native service type '{name}' cannot be deleted"
        )
    # Block deletion if any role still references this type
    usage = await fetch_one(
        "SELECT COUNT(*) AS c FROM roles WHERE $1 = ANY(service_types)",
        name,
    )
    if usage is not None and usage["c"] > 0:
        raise ServiceTypeInUseError(
            f"Service type '{name}' is still used by {usage['c']} role(s)"
        )
    result = await execute(
        "DELETE FROM service_types WHERE name = $1", name
    )
    if result == "DELETE 0":
        raise ServiceTypeNotFoundError(f"Service type '{name}' not found")
    _log.info("service_types.delete", name=name)


async def validate_names(names: list[str]) -> list[str]:
    """Return the subset of `names` that do NOT exist in service_types."""
    if not names:
        return []
    rows = await fetch_all(
        "SELECT name FROM service_types WHERE name = ANY($1::text[])",
        names,
    )
    valid = {r["name"] for r in rows}
    return [n for n in names if n not in valid]
