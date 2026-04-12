from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog

from agflow.auth.api_key import generate_api_key
from agflow.config import get_settings
from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.api_keys import ApiKeyCreated, ApiKeySummary

_log = structlog.get_logger(__name__)

ALL_SCOPES: set[str] = {
    "*",
    "platform_secrets:read",
    "platform_secrets:write",
    "user_secrets:read",
    "user_secrets:write",
    "dockerfiles:read",
    "dockerfiles:write",
    "dockerfiles:delete",
    "dockerfiles:build",
    "dockerfiles.files:read",
    "dockerfiles.files:write",
    "dockerfiles.files:delete",
    "dockerfiles.params:read",
    "dockerfiles.params:write",
    "discovery:read",
    "discovery:write",
    "service_types:read",
    "service_types:write",
    "users:manage",
    "roles:read",
    "roles:write",
    "roles:delete",
    "catalogs:read",
    "catalogs:write",
    "agents:read",
    "agents:write",
    "agents:delete",
    "agents:run",
    "containers:read",
    "containers:run",
    "containers:stop",
    "containers.logs:read",
    "containers.chat:write",
    "keys:manage",
}

_EXPIRY_MAP: dict[str, timedelta | None] = {
    "3m": timedelta(days=90),
    "6m": timedelta(days=180),
    "9m": timedelta(days=270),
    "12m": timedelta(days=365),
    "never": None,
}

_KEY_COLS = """
    id, owner_id, name, prefix, scopes, rate_limit,
    expires_at, revoked, created_at, last_used_at
"""


class ApiKeyNotFoundError(Exception):
    pass


class InvalidScopesError(Exception):
    pass


def compute_expiry(expires_in: str) -> datetime | None:
    delta = _EXPIRY_MAP.get(expires_in)
    if delta is None:
        return None
    return datetime.now(UTC) + delta


def validate_key_scopes(
    user_role: str,
    user_scopes: list[str],
    requested_scopes: list[str],
) -> list[str]:
    """Return list of rejected scopes (scopes user cannot grant).

    Admin can grant any scope — always returns [].
    Regular users can only grant their own scopes plus the implicit keys:manage.
    """
    if user_role == "admin":
        return []
    allowed = set(user_scopes) | {"keys:manage"}
    return [s for s in requested_scopes if s not in allowed]


def _row_to_summary(row: dict[str, Any]) -> ApiKeySummary:
    return ApiKeySummary(
        id=row["id"],
        owner_id=row["owner_id"],
        name=row["name"],
        prefix=row["prefix"],
        scopes=list(row["scopes"]) if row["scopes"] else [],
        rate_limit=row["rate_limit"],
        expires_at=row.get("expires_at"),
        revoked=row["revoked"],
        created_at=row["created_at"],
        last_used_at=row.get("last_used_at"),
    )


async def create(
    name: str,
    scopes: list[str],
    rate_limit: int,
    expires_at: datetime | None,
    owner_id: UUID,
) -> ApiKeyCreated:
    settings = get_settings()
    full_key, prefix, key_hash = generate_api_key(settings.api_key_salt, expires_at)

    row = await fetch_one(
        """
        INSERT INTO api_keys (owner_id, name, prefix, key_hash, scopes, rate_limit, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id, name, prefix, scopes, rate_limit, expires_at, created_at
        """,
        owner_id,
        name,
        prefix,
        key_hash,
        scopes,
        rate_limit,
        expires_at,
    )
    assert row is not None
    _log.info("api_keys.create", owner_id=str(owner_id), prefix=prefix)
    return ApiKeyCreated(
        id=row["id"],
        name=row["name"],
        prefix=row["prefix"],
        full_key=full_key,
        scopes=list(row["scopes"]) if row["scopes"] else [],
        rate_limit=row["rate_limit"],
        expires_at=row.get("expires_at"),
        created_at=row["created_at"],
    )


async def list_all(owner_id: UUID | None = None) -> list[ApiKeySummary]:
    if owner_id is not None:
        rows = await fetch_all(
            f"SELECT {_KEY_COLS} FROM api_keys WHERE owner_id = $1 ORDER BY created_at DESC",
            owner_id,
        )
    else:
        rows = await fetch_all(
            f"SELECT {_KEY_COLS} FROM api_keys ORDER BY created_at DESC"
        )
    return [_row_to_summary(r) for r in rows]


async def get_by_id(key_id: UUID) -> ApiKeySummary:
    row = await fetch_one(
        f"SELECT {_KEY_COLS} FROM api_keys WHERE id = $1",
        key_id,
    )
    if row is None:
        raise ApiKeyNotFoundError(f"API key {key_id} not found")
    return _row_to_summary(row)


async def get_by_prefix(prefix: str) -> dict[str, Any] | None:
    return await fetch_one(
        """
        SELECT id, owner_id, name, prefix, key_hash, scopes, rate_limit,
               expires_at, revoked, created_at, last_used_at
        FROM api_keys
        WHERE prefix = $1
        """,
        prefix,
    )


async def update(
    key_id: UUID,
    name: str | None = None,
    scopes: list[str] | None = None,
    rate_limit: int | None = None,
) -> ApiKeySummary:
    sets: list[str] = []
    args: list[Any] = []
    idx = 1
    if name is not None:
        sets.append(f"name = ${idx}")
        args.append(name)
        idx += 1
    if scopes is not None:
        sets.append(f"scopes = ${idx}")
        args.append(scopes)
        idx += 1
    if rate_limit is not None:
        sets.append(f"rate_limit = ${idx}")
        args.append(rate_limit)
        idx += 1
    if not sets:
        return await get_by_id(key_id)
    args.append(key_id)
    query = f"UPDATE api_keys SET {', '.join(sets)} WHERE id = ${idx} RETURNING id"
    row = await fetch_one(query, *args)
    if row is None:
        raise ApiKeyNotFoundError(f"API key {key_id} not found")
    _log.info("api_keys.update", key_id=str(key_id))
    return await get_by_id(key_id)


async def revoke(key_id: UUID) -> None:
    row = await fetch_one(
        "UPDATE api_keys SET revoked = TRUE WHERE id = $1 RETURNING id",
        key_id,
    )
    if row is None:
        raise ApiKeyNotFoundError(f"API key {key_id} not found")
    _log.info("api_keys.revoke", key_id=str(key_id))


async def update_last_used(key_id: UUID) -> None:
    await execute(
        "UPDATE api_keys SET last_used_at = NOW() WHERE id = $1",
        key_id,
    )
