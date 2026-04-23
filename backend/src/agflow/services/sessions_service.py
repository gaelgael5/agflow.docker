from __future__ import annotations

from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)

_COLS = "id, api_key_id, name, status, project_id, created_at, expires_at, closed_at"


async def create(
    *,
    api_key_id: UUID,
    name: str | None,
    duration_seconds: int,
    project_id: str | None = None,
) -> dict:
    row = await fetch_one(
        f"""
        INSERT INTO sessions (api_key_id, name, project_id, expires_at)
        VALUES ($1, $2, $3, now() + ($4 || ' seconds')::interval)
        RETURNING {_COLS}
        """,
        api_key_id,
        name,
        project_id,
        str(duration_seconds),
    )
    _log.info(
        "sessions.created",
        session_id=str(row["id"]),
        api_key_id=str(api_key_id),
        project_id=project_id,
        duration_seconds=duration_seconds,
    )
    return dict(row)


async def get(
    *,
    session_id: UUID,
    api_key_id: UUID,
    is_admin: bool,
) -> dict | None:
    if is_admin:
        row = await fetch_one(
            f"SELECT {_COLS} FROM sessions WHERE id = $1",
            session_id,
        )
    else:
        row = await fetch_one(
            f"SELECT {_COLS} FROM sessions WHERE id = $1 AND api_key_id = $2",
            session_id,
            api_key_id,
        )
    return dict(row) if row else None


async def list_for_key(*, api_key_id: UUID, is_admin: bool) -> list[dict]:
    if is_admin:
        rows = await fetch_all(
            f"SELECT {_COLS} FROM sessions ORDER BY created_at DESC",
        )
    else:
        rows = await fetch_all(
            f"SELECT {_COLS} FROM sessions WHERE api_key_id = $1 ORDER BY created_at DESC",
            api_key_id,
        )
    return [dict(r) for r in rows]


async def extend(
    *,
    session_id: UUID,
    api_key_id: UUID,
    is_admin: bool,
    additional_seconds: int,
) -> dict | None:
    if is_admin:
        row = await fetch_one(
            f"""
            UPDATE sessions
            SET expires_at = expires_at + ($1 || ' seconds')::interval
            WHERE id = $2 AND status = 'active'
            RETURNING {_COLS}
            """,
            str(additional_seconds),
            session_id,
        )
    else:
        row = await fetch_one(
            f"""
            UPDATE sessions
            SET expires_at = expires_at + ($1 || ' seconds')::interval
            WHERE id = $2 AND status = 'active' AND api_key_id = $3
            RETURNING {_COLS}
            """,
            str(additional_seconds),
            session_id,
            api_key_id,
        )
    return dict(row) if row else None


async def close(
    *,
    session_id: UUID,
    api_key_id: UUID,
    is_admin: bool,
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
            session_id,
            api_key_id,
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


async def list_all_with_counts() -> list[dict]:
    """Admin-scoped list : toutes les sessions + count des agents actifs.

    Renvoie tous les champs de `_COLS` enrichis de `agent_count` (int).
    Tri : `created_at DESC`.
    """
    rows = await fetch_all(
        """
        SELECT
            s.id, s.api_key_id, s.name, s.status, s.project_id,
            s.created_at, s.expires_at, s.closed_at,
            COUNT(ai.id) FILTER (WHERE ai.destroyed_at IS NULL) AS agent_count
        FROM sessions s
        LEFT JOIN agents_instances ai ON ai.session_id = s.id
        GROUP BY s.id
        ORDER BY s.created_at DESC
        """,
    )
    return [dict(r) for r in rows]
