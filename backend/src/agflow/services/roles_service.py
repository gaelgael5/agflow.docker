from __future__ import annotations

from typing import Any

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one, get_pool
from agflow.schemas.roles import RoleSummary
from agflow.services import role_files_service

_log = structlog.get_logger(__name__)

_ROLE_DB_COLS = "id, created_at, updated_at"


class RoleNotFoundError(Exception):
    pass


class DuplicateRoleError(Exception):
    pass


class InvalidServiceTypeError(Exception):
    pass


def _row_to_summary(row: dict[str, Any]) -> RoleSummary:
    role_id = row["id"]
    meta = role_files_service.read_meta(role_id)
    return RoleSummary(
        id=role_id,
        display_name=meta.get("display_name", role_id),
        description=meta.get("description", ""),
        service_types=meta.get("service_types", []),
        identity_md=role_files_service.read_identity(role_id),
        prompt_orchestrator_md=role_files_service.read_prompt_orchestrator(role_id),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _validate_service_types(names: list[str]) -> None:
    if not names:
        return
    from agflow.services import service_types_service
    unknown = await service_types_service.validate_names(names)
    if unknown:
        raise InvalidServiceTypeError(
            f"Unknown service types: {', '.join(sorted(unknown))}"
        )


async def create(
    role_id: str,
    display_name: str,
    description: str = "",
    service_types: list[str] | None = None,
    identity_md: str = "",
) -> RoleSummary:
    await _validate_service_types(service_types or [])
    try:
        row = await fetch_one(
            f"INSERT INTO roles (id) VALUES ($1) RETURNING {_ROLE_DB_COLS}",
            role_id,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateRoleError(f"Role '{role_id}' already exists") from exc
    assert row is not None

    role_files_service.write_meta(role_id, {
        "display_name": display_name,
        "description": description,
        "service_types": service_types or [],
    })
    role_files_service.write_identity(role_id, identity_md)

    from agflow.services import role_sections_service
    await role_sections_service.seed_natives(role_id)
    _log.info("roles.create", role_id=role_id)
    return _row_to_summary(row)


async def list_all() -> list[RoleSummary]:
    rows = await fetch_all(
        f"SELECT {_ROLE_DB_COLS} FROM roles ORDER BY id ASC"
    )
    return [_row_to_summary(r) for r in rows]


async def get_by_id(role_id: str) -> RoleSummary:
    row = await fetch_one(
        f"SELECT {_ROLE_DB_COLS} FROM roles WHERE id = $1", role_id
    )
    if row is None:
        raise RoleNotFoundError(f"Role '{role_id}' not found")
    return _row_to_summary(row)


async def update(role_id: str, **fields: Any) -> RoleSummary:
    row = await fetch_one(
        f"SELECT {_ROLE_DB_COLS} FROM roles WHERE id = $1", role_id
    )
    if row is None:
        raise RoleNotFoundError(f"Role '{role_id}' not found")

    if "service_types" in fields and fields["service_types"] is not None:
        await _validate_service_types(fields["service_types"])

    # Update disk files
    meta = role_files_service.read_meta(role_id)
    changed = False
    for key in ("display_name", "description", "service_types"):
        if key in fields and fields[key] is not None:
            meta[key] = fields[key]
            changed = True
    if changed:
        role_files_service.write_meta(role_id, meta)

    if "identity_md" in fields and fields["identity_md"] is not None:
        role_files_service.write_identity(role_id, fields["identity_md"])
        changed = True

    if changed:
        await execute(
            "UPDATE roles SET updated_at = NOW() WHERE id = $1", role_id
        )
        row = await fetch_one(
            f"SELECT {_ROLE_DB_COLS} FROM roles WHERE id = $1", role_id
        )

    _log.info("roles.update", role_id=role_id, fields=list(fields.keys()))
    return _row_to_summary(row)


async def update_prompts(
    role_id: str,
    prompt_orchestrator_md: str,
) -> RoleSummary:
    row = await fetch_one(
        f"SELECT {_ROLE_DB_COLS} FROM roles WHERE id = $1", role_id
    )
    if row is None:
        raise RoleNotFoundError(f"Role '{role_id}' not found")

    role_files_service.write_prompt_orchestrator(role_id, prompt_orchestrator_md)
    await execute(
        "UPDATE roles SET updated_at = NOW() WHERE id = $1", role_id
    )
    row = await fetch_one(
        f"SELECT {_ROLE_DB_COLS} FROM roles WHERE id = $1", role_id
    )
    _log.info("roles.update_prompts", role_id=role_id)
    return _row_to_summary(row)


async def delete(role_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM roles WHERE id = $1", role_id)
    if result == "DELETE 0":
        raise RoleNotFoundError(f"Role '{role_id}' not found")
    role_files_service.delete_role_dir(role_id)
    _log.info("roles.delete", role_id=role_id)
