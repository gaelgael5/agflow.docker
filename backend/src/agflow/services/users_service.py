from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.users import UserSummary

_log = structlog.get_logger(__name__)

_USER_COLS = """
    u.id, u.email, u.name, u.avatar_url, u.role, u.scopes, u.status,
    u.created_at, u.approved_at, u.last_login
"""


class UserNotFoundError(Exception):
    pass


class DuplicateUserError(Exception):
    pass


def _row_to_summary(row: dict[str, Any]) -> UserSummary:
    return UserSummary(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        avatar_url=row["avatar_url"],
        role=row["role"],
        scopes=list(row["scopes"]) if row["scopes"] else [],
        status=row["status"],
        created_at=row["created_at"],
        approved_at=row.get("approved_at"),
        last_login=row.get("last_login"),
        api_key_count=row.get("api_key_count", 0),
    )


async def list_all() -> list[UserSummary]:
    rows = await fetch_all(
        f"""
        SELECT
            {_USER_COLS},
            (SELECT COUNT(*) FROM api_keys ak WHERE ak.owner_id = u.id) AS api_key_count
        FROM users u
        ORDER BY
            CASE u.status
                WHEN 'pending'  THEN 0
                WHEN 'active'   THEN 1
                WHEN 'disabled' THEN 2
                ELSE 3
            END,
            u.created_at ASC
        """
    )
    return [_row_to_summary(r) for r in rows]


async def get_by_id(user_id: UUID) -> UserSummary:
    row = await fetch_one(
        f"""
        SELECT
            {_USER_COLS},
            (SELECT COUNT(*) FROM api_keys ak WHERE ak.owner_id = u.id) AS api_key_count
        FROM users u
        WHERE u.id = $1
        """,
        user_id,
    )
    if row is None:
        raise UserNotFoundError(f"User {user_id} not found")
    return _row_to_summary(row)


async def get_by_email(email: str) -> UserSummary | None:
    row = await fetch_one(
        f"""
        SELECT
            {_USER_COLS},
            (SELECT COUNT(*) FROM api_keys ak WHERE ak.owner_id = u.id) AS api_key_count
        FROM users u
        WHERE u.email = $1
        """,
        email,
    )
    if row is None:
        return None
    return _row_to_summary(row)


async def create(
    email: str,
    name: str = "",
    role: str = "user",
    scopes: list[str] | None = None,
    status: str = "active",
) -> UserSummary:
    effective_scopes: list[str] = scopes if scopes is not None else []
    try:
        row = await fetch_one(
            """
            INSERT INTO users (email, name, role, scopes, status)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            email,
            name,
            role,
            effective_scopes,
            status,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateUserError(f"User '{email}' already exists") from exc
    assert row is not None
    _log.info("users.create", email=email, role=role)
    return await get_by_id(row["id"])


async def update(
    user_id: UUID,
    name: str | None = None,
    role: str | None = None,
    scopes: list[str] | None = None,
) -> UserSummary:
    sets: list[str] = []
    args: list[Any] = []
    idx = 1
    if name is not None:
        sets.append(f"name = ${idx}")
        args.append(name)
        idx += 1
    if role is not None:
        sets.append(f"role = ${idx}")
        args.append(role)
        idx += 1
    if scopes is not None:
        sets.append(f"scopes = ${idx}")
        args.append(scopes)
        idx += 1
    if not sets:
        return await get_by_id(user_id)
    args.append(user_id)
    query = f"""
        UPDATE users SET {", ".join(sets)}
        WHERE id = ${idx}
        RETURNING id
    """
    row = await fetch_one(query, *args)
    if row is None:
        raise UserNotFoundError(f"User {user_id} not found")
    _log.info("users.update", user_id=str(user_id))
    return await get_by_id(user_id)


async def approve(user_id: UUID, approved_by: UUID) -> UserSummary:
    row = await fetch_one(
        """
        UPDATE users
        SET status = 'active', approved_at = NOW(), approved_by = $2
        WHERE id = $1
        RETURNING id
        """,
        user_id,
        approved_by,
    )
    if row is None:
        raise UserNotFoundError(f"User {user_id} not found")
    _log.info("users.approve", user_id=str(user_id), approved_by=str(approved_by))
    return await get_by_id(user_id)


async def disable(user_id: UUID) -> UserSummary:
    row = await fetch_one(
        """
        UPDATE users SET status = 'disabled'
        WHERE id = $1
        RETURNING id
        """,
        user_id,
    )
    if row is None:
        raise UserNotFoundError(f"User {user_id} not found")
    _log.info("users.disable", user_id=str(user_id))
    return await get_by_id(user_id)


async def enable(user_id: UUID) -> UserSummary:
    row = await fetch_one(
        """
        UPDATE users SET status = 'active'
        WHERE id = $1
        RETURNING id
        """,
        user_id,
    )
    if row is None:
        raise UserNotFoundError(f"User {user_id} not found")
    _log.info("users.enable", user_id=str(user_id))
    return await get_by_id(user_id)


async def delete(user_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM users WHERE id = $1", user_id)
    if result == "DELETE 0":
        raise UserNotFoundError(f"User {user_id} not found")
    _log.info("users.delete", user_id=str(user_id))


async def seed_admin(email: str) -> None:
    existing = await get_by_email(email)
    if existing is not None:
        _log.info("users.seed_admin.already_exists", email=email)
        return
    await create(email=email, name="Admin", role="admin", status="active")
    _log.info("users.seed_admin.created", email=email)
