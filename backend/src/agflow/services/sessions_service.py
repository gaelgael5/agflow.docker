from __future__ import annotations

from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)


async def create(
    *, api_key_id: UUID, name: str | None, duration_seconds: int,
) -> dict:
    row = await fetch_one(
        """
        INSERT INTO sessions (api_key_id, name, expires_at)
        VALUES ($1, $2, now() + ($3 || ' seconds')::interval)
        RETURNING id, api_key_id, name, status, created_at, expires_at, closed_at
        """,
        api_key_id, name, str(duration_seconds),
    )
    _log.info(
        "sessions.created",
        session_id=str(row["id"]),
        api_key_id=str(api_key_id),
        duration_seconds=duration_seconds,
    )
    return dict(row)


async def get(
    *, session_id: UUID, api_key_id: UUID, is_admin: bool,
) -> dict | None:
    if is_admin:
        row = await fetch_one(
            "SELECT id, api_key_id, name, status, created_at, expires_at, closed_at "
            "FROM sessions WHERE id = $1",
            session_id,
        )
    else:
        row = await fetch_one(
            "SELECT id, api_key_id, name, status, created_at, expires_at, closed_at "
            "FROM sessions WHERE id = $1 AND api_key_id = $2",
            session_id, api_key_id,
        )
    return dict(row) if row else None


async def list_for_key(*, api_key_id: UUID, is_admin: bool) -> list[dict]:
    if is_admin:
        rows = await fetch_all(
            "SELECT id, api_key_id, name, status, created_at, expires_at, closed_at "
            "FROM sessions ORDER BY created_at DESC",
        )
    else:
        rows = await fetch_all(
            "SELECT id, api_key_id, name, status, created_at, expires_at, closed_at "
            "FROM sessions WHERE api_key_id = $1 ORDER BY created_at DESC",
            api_key_id,
        )
    return [dict(r) for r in rows]


async def extend(
    *, session_id: UUID, api_key_id: UUID, is_admin: bool, additional_seconds: int,
) -> dict | None:
    if is_admin:
        row = await fetch_one(
            """
            UPDATE sessions
            SET expires_at = expires_at + ($1 || ' seconds')::interval
            WHERE id = $2 AND status = 'active'
            RETURNING id, api_key_id, name, status, created_at, expires_at, closed_at
            """,
            str(additional_seconds), session_id,
        )
    else:
        row = await fetch_one(
            """
            UPDATE sessions
            SET expires_at = expires_at + ($1 || ' seconds')::interval
            WHERE id = $2 AND status = 'active' AND api_key_id = $3
            RETURNING id, api_key_id, name, status, created_at, expires_at, closed_at
            """,
            str(additional_seconds), session_id, api_key_id,
        )
    return dict(row) if row else None


async def close(
    *, session_id: UUID, api_key_id: UUID, is_admin: bool,
) -> bool:
    if is_admin:
        result = await execute(
            """
            UPDATE sessions
            SET status = 'closed', closed_at = now()
            WHERE id = $1 AND status = 'active'
            """,
            session_id,
        )
    else:
        result = await execute(
            """
            UPDATE sessions
            SET status = 'closed', closed_at = now()
            WHERE id = $1 AND status = 'active' AND api_key_id = $2
            """,
            session_id, api_key_id,
        )
    closed = result.endswith(" 1")
    if closed:
        _log.info("sessions.closed", session_id=str(session_id))
    return closed


async def expire_stale() -> int:
    result = await execute(
        """
        UPDATE sessions
        SET status = 'expired', closed_at = now()
        WHERE status = 'active' AND expires_at < now()
        """,
    )
    count = int(result.split()[-1]) if result else 0
    if count > 0:
        _log.info("sessions.expired", count=count)
    return count
