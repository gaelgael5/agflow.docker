from __future__ import annotations

from typing import Literal
from uuid import UUID

import asyncpg
import structlog

from agflow.config import get_settings
from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.secrets import Scope, SecretReveal, SecretSummary

_log = structlog.get_logger(__name__)


class SecretNotFoundError(Exception):
    pass


class DuplicateSecretError(Exception):
    pass


async def create(
    var_name: str,
    value: str,
    scope: Scope = "global",
    agent_id: UUID | None = None,
) -> SecretSummary:
    master = get_settings().secrets_master_key
    try:
        row = await fetch_one(
            """
            INSERT INTO secrets (var_name, value_encrypted, scope, agent_id)
            VALUES ($1, pgp_sym_encrypt($2, $3), $4, $5)
            RETURNING id, var_name, scope, created_at, updated_at
            """,
            var_name,
            value,
            master,
            scope,
            agent_id,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateSecretError(
            f"Secret '{var_name}' already exists in scope '{scope}'"
        ) from exc
    assert row is not None
    _log.info("secrets.create", var_name=var_name, scope=scope)
    return SecretSummary(**row, used_by=[])


async def list_all() -> list[SecretSummary]:
    rows = await fetch_all(
        """
        SELECT id, var_name, scope, created_at, updated_at
        FROM secrets
        ORDER BY var_name ASC
        """
    )
    return [SecretSummary(**r, used_by=[]) for r in rows]


async def get_by_id(secret_id: UUID) -> SecretSummary:
    row = await fetch_one(
        "SELECT id, var_name, scope, created_at, updated_at FROM secrets WHERE id = $1",
        secret_id,
    )
    if row is None:
        raise SecretNotFoundError(f"Secret {secret_id} not found")
    return SecretSummary(**row, used_by=[])


async def reveal(secret_id: UUID) -> SecretReveal:
    master = get_settings().secrets_master_key
    row = await fetch_one(
        """
        SELECT id, var_name, pgp_sym_decrypt(value_encrypted, $2) AS value
        FROM secrets
        WHERE id = $1
        """,
        secret_id,
        master,
    )
    if row is None:
        raise SecretNotFoundError(f"Secret {secret_id} not found")
    _log.info("secrets.reveal", secret_id=str(secret_id), var_name=row["var_name"])
    return SecretReveal(id=row["id"], var_name=row["var_name"], value=row["value"])


async def update(
    secret_id: UUID,
    value: str | None = None,
    scope: Scope | None = None,
) -> SecretSummary:
    master = get_settings().secrets_master_key
    sets: list[str] = []
    args: list[object] = []
    idx = 1
    if value is not None:
        sets.append(f"value_encrypted = pgp_sym_encrypt(${idx}, ${idx + 1})")
        args.extend([value, master])
        idx += 2
    if scope is not None:
        sets.append(f"scope = ${idx}")
        args.append(scope)
        idx += 1
    if not sets:
        return await get_by_id(secret_id)
    sets.append("updated_at = NOW()")
    args.append(secret_id)
    query = f"""
        UPDATE secrets SET {", ".join(sets)}
        WHERE id = ${idx}
        RETURNING id, var_name, scope, created_at, updated_at
    """
    row = await fetch_one(query, *args)
    if row is None:
        raise SecretNotFoundError(f"Secret {secret_id} not found")
    _log.info("secrets.update", secret_id=str(secret_id))
    return SecretSummary(**row, used_by=[])


async def delete(secret_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM secrets WHERE id = $1", secret_id)
    if result == "DELETE 0":
        raise SecretNotFoundError(f"Secret {secret_id} not found")
    _log.info("secrets.delete", secret_id=str(secret_id))


async def resolve_env(var_names: list[str]) -> dict[str, str]:
    """Resolve alias names to their plaintext values. Raises if any are missing."""
    master = get_settings().secrets_master_key
    rows = await fetch_all(
        """
        SELECT var_name, pgp_sym_decrypt(value_encrypted, $2) AS value
        FROM secrets
        WHERE var_name = ANY($1::text[]) AND scope = 'global'
        """,
        var_names,
        master,
    )
    resolved = {r["var_name"]: r["value"] for r in rows}
    missing = [n for n in var_names if n not in resolved]
    if missing:
        raise SecretNotFoundError(f"Missing secrets: {', '.join(missing)}")
    return resolved


async def resolve_status(
    var_names: list[str],
) -> dict[str, Literal["ok", "empty", "missing"]]:
    """Return status for each requested variable (for visual indicators 🔴🟠🟢)."""
    master = get_settings().secrets_master_key
    rows = await fetch_all(
        """
        SELECT var_name, pgp_sym_decrypt(value_encrypted, $2) AS value
        FROM secrets
        WHERE var_name = ANY($1::text[]) AND scope = 'global'
        """,
        var_names,
        master,
    )
    present = {r["var_name"]: r["value"] for r in rows}
    result: dict[str, Literal["ok", "empty", "missing"]] = {}
    for name in var_names:
        if name not in present:
            result[name] = "missing"
        elif not present[name].strip():
            result[name] = "empty"
        else:
            result[name] = "ok"
    return result
