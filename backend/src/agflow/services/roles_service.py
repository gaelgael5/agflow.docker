from __future__ import annotations

import json
from typing import Any

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.roles import RoleSummary

_log = structlog.get_logger(__name__)

_ROLE_COLS = (
    "id, display_name, description, service_types, identity_md, "
    "prompt_orchestrator_md, runtime_config, created_at, updated_at"
)


class RoleNotFoundError(Exception):
    pass


class DuplicateRoleError(Exception):
    pass


def _row_to_summary(row: dict[str, Any]) -> RoleSummary:
    runtime_config = row["runtime_config"]
    if isinstance(runtime_config, str):
        runtime_config = json.loads(runtime_config) if runtime_config else {}
    return RoleSummary(
        id=row["id"],
        display_name=row["display_name"],
        description=row["description"],
        service_types=list(row["service_types"]),
        identity_md=row["identity_md"],
        prompt_orchestrator_md=row["prompt_orchestrator_md"],
        runtime_config=runtime_config or {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class InvalidServiceTypeError(Exception):
    pass


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
            f"""
            INSERT INTO roles (
                id, display_name, description, service_types, identity_md
            )
            VALUES ($1, $2, $3, $4, $5)
            RETURNING {_ROLE_COLS}
            """,
            role_id,
            display_name,
            description,
            service_types or [],
            identity_md,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateRoleError(f"Role '{role_id}' already exists") from exc
    assert row is not None
    # Auto-seed the 3 native sections for the new role so that document
    # creation (which FK-references role_sections) can proceed immediately.
    from agflow.services import role_sections_service
    await role_sections_service.seed_natives(role_id)
    _log.info("roles.create", role_id=role_id)
    return _row_to_summary(row)


async def list_all() -> list[RoleSummary]:
    rows = await fetch_all(
        f"SELECT {_ROLE_COLS} FROM roles ORDER BY display_name ASC"
    )
    return [_row_to_summary(r) for r in rows]


async def get_by_id(role_id: str) -> RoleSummary:
    row = await fetch_one(
        f"SELECT {_ROLE_COLS} FROM roles WHERE id = $1", role_id
    )
    if row is None:
        raise RoleNotFoundError(f"Role '{role_id}' not found")
    return _row_to_summary(row)


async def update(role_id: str, **fields: Any) -> RoleSummary:
    allowed = {
        "display_name",
        "description",
        "service_types",
        "identity_md",
        "runtime_config",
    }
    if "service_types" in fields and fields["service_types"] is not None:
        await _validate_service_types(fields["service_types"])
    sets: list[str] = []
    args: list[Any] = []
    idx = 1
    for key, value in fields.items():
        if value is None or key not in allowed:
            continue
        sets.append(f"{key} = ${idx}")
        args.append(value)
        idx += 1
    if not sets:
        return await get_by_id(role_id)
    sets.append("updated_at = NOW()")
    args.append(role_id)
    query = (
        f"UPDATE roles SET {', '.join(sets)} "
        f"WHERE id = ${idx} RETURNING {_ROLE_COLS}"
    )
    row = await fetch_one(query, *args)
    if row is None:
        raise RoleNotFoundError(f"Role '{role_id}' not found")
    _log.info("roles.update", role_id=role_id, fields=list(fields.keys()))
    return _row_to_summary(row)


async def update_prompts(
    role_id: str,
    prompt_orchestrator_md: str,
) -> RoleSummary:
    row = await fetch_one(
        f"""
        UPDATE roles SET
            prompt_orchestrator_md = $2,
            updated_at = NOW()
        WHERE id = $1
        RETURNING {_ROLE_COLS}
        """,
        role_id,
        prompt_orchestrator_md,
    )
    if row is None:
        raise RoleNotFoundError(f"Role '{role_id}' not found")
    _log.info("roles.update_prompts", role_id=role_id)
    return _row_to_summary(row)


async def delete(role_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM roles WHERE id = $1", role_id)
    if result == "DELETE 0":
        raise RoleNotFoundError(f"Role '{role_id}' not found")
    _log.info("roles.delete", role_id=role_id)
