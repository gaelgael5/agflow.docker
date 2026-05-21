"""group_variables — variables globales partagées au niveau d'un groupe.

Stocke un mapping `(name → value)` par groupe. La `value` peut être :
    - une valeur littérale,
    - une référence déclarative ${vault://api:path} ou ${env://NAME}.

Au Generate, project_deployments_service injecte ces variables dans le .env
du déploiement après avoir résolu les éventuelles refs via
platform_secrets_service.resolve_platform_refs.

Le nom (`name`) doit respecter la convention shell `[A-Za-z_][A-Za-z0-9_]*`
pour pouvoir être consommé via `${NAME}` dans un script bash sans surprise.
La validation se fait au niveau service (la DB accepte des chaînes plus larges
pour le cas où on voudrait des alias non-conformes — pas le cas en V1).
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.group_variables import GroupVariableRow

_log = structlog.get_logger(__name__)

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class GroupVariableNotFoundError(Exception):
    pass


class GroupVariableInvalidNameError(ValueError):
    """Le nom ne respecte pas la convention shell `[A-Za-z_][A-Za-z0-9_]*`."""


class GroupVariableDuplicateError(Exception):
    """Une variable de ce nom existe déjà dans le groupe."""


def _validate_name(name: str) -> None:
    if not _NAME_RE.match(name or ""):
        raise GroupVariableInvalidNameError(
            f"name {name!r} doit matcher [A-Za-z_][A-Za-z0-9_]* "
            "(convention shell — pas de tirets, espaces, etc.)"
        )


def _to_row(row: dict[str, Any]) -> GroupVariableRow:
    return GroupVariableRow(
        id=row["id"],
        group_id=row["group_id"],
        name=row["name"],
        value=row["value"] or "",
        description=row["description"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_by_group(group_id: UUID) -> list[GroupVariableRow]:
    rows = await fetch_all(
        "SELECT id, group_id, name, value, description, created_at, updated_at "
        "FROM group_variables WHERE group_id = $1 ORDER BY name",
        group_id,
    )
    return [_to_row(r) for r in rows]


async def get_by_id(var_id: UUID) -> GroupVariableRow:
    row = await fetch_one(
        "SELECT id, group_id, name, value, description, created_at, updated_at "
        "FROM group_variables WHERE id = $1",
        var_id,
    )
    if row is None:
        raise GroupVariableNotFoundError(f"group_variable {var_id} not found")
    return _to_row(row)


async def create(
    group_id: UUID,
    name: str,
    value: str = "",
    description: str = "",
) -> GroupVariableRow:
    import asyncpg

    _validate_name(name)
    try:
        row = await fetch_one(
            "INSERT INTO group_variables (group_id, name, value, description) "
            "VALUES ($1, $2, $3, $4) "
            "RETURNING id, group_id, name, value, description, created_at, updated_at",
            group_id, name, value, description,
        )
    except asyncpg.UniqueViolationError as exc:
        raise GroupVariableDuplicateError(
            f"group_variable {name!r} already exists for this group"
        ) from exc
    assert row is not None
    _log.info("group_variables.create", group_id=str(group_id), name=name)
    return _to_row(row)


async def update(
    var_id: UUID,
    *,
    name: str | None = None,
    value: str | None = None,
    description: str | None = None,
) -> GroupVariableRow:
    """Met à jour une variable. Les champs `None` sont ignorés."""
    import asyncpg

    if name is not None:
        _validate_name(name)

    current = await get_by_id(var_id)

    next_name = name if name is not None else current.name
    next_value = value if value is not None else current.value
    next_description = description if description is not None else current.description

    try:
        row = await fetch_one(
            "UPDATE group_variables SET name = $2, value = $3, description = $4 "
            "WHERE id = $1 "
            "RETURNING id, group_id, name, value, description, created_at, updated_at",
            var_id, next_name, next_value, next_description,
        )
    except asyncpg.UniqueViolationError as exc:
        raise GroupVariableDuplicateError(
            f"another group_variable already uses the name {next_name!r}"
        ) from exc
    assert row is not None
    _log.info("group_variables.update", id=str(var_id), name=next_name)
    return _to_row(row)


async def delete(var_id: UUID) -> None:
    result = await execute("DELETE FROM group_variables WHERE id = $1", var_id)
    if result.endswith(" 0"):
        raise GroupVariableNotFoundError(f"group_variable {var_id} not found")
    _log.info("group_variables.delete", id=str(var_id))


async def as_mapping(group_id: UUID) -> dict[str, str]:
    """Helper pour le moteur Generate : retourne `{name: raw_value}` pour ce groupe.

    Les refs `${vault://...}` / `${env://...}` ne sont PAS résolues ici — le
    moteur s'en charge via platform_secrets_service.resolve_platform_refs avant
    d'écrire dans le .env du déploiement.
    """
    rows = await list_by_group(group_id)
    return {r.name: r.value for r in rows}
