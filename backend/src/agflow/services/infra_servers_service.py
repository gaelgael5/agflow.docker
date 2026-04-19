"""Infrastructure servers service — asyncpg CRUD.

Passwords are encrypted at rest via crypto_service (Fernet).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import fetch_all, fetch_one
from agflow.schemas.infra import ServerSummary
from agflow.services import crypto_service

_log = structlog.get_logger(__name__)

_COLS = "id, name, type, host, port, username, password, certificate_id, created_at, updated_at"


class ServerNotFoundError(Exception):
    pass


def _to_summary(row: dict[str, Any]) -> ServerSummary:
    return ServerSummary(
        id=row["id"],
        name=row.get("name", ""),
        type=row["type"],
        host=row["host"],
        port=row["port"],
        username=row["username"],
        has_password=bool(row.get("password")),
        certificate_id=row.get("certificate_id"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_all() -> list[ServerSummary]:
    rows = await fetch_all(f"SELECT {_COLS} FROM infra_servers ORDER BY host")
    results = []
    for r in rows:
        summary = _to_summary(r)
        # Count machines
        count_row = await fetch_one(
            "SELECT count(*) as cnt FROM infra_machines WHERE server_id = $1", r["id"],
        )
        summary.machine_count = count_row["cnt"] if count_row else 0
        results.append(summary)
    return results


async def get_by_id(server_id: UUID) -> ServerSummary:
    row = await fetch_one(f"SELECT {_COLS} FROM infra_servers WHERE id = $1", server_id)
    if row is None:
        raise ServerNotFoundError(f"Server {server_id} not found")
    return _to_summary(row)


async def get_credentials(server_id: UUID) -> dict[str, Any]:
    """Return decrypted credentials for SSH use."""
    row = await fetch_one(f"SELECT {_COLS} FROM infra_servers WHERE id = $1", server_id)
    if row is None:
        raise ServerNotFoundError(f"Server {server_id} not found")
    return {
        "host": row["host"],
        "port": row["port"],
        "username": row["username"],
        "password": crypto_service.decrypt(row["password"]),
        "certificate_id": row.get("certificate_id"),
    }


async def create(
    server_type: str,
    host: str,
    port: int = 22,
    username: str | None = None,
    password: str | None = None,
    certificate_id: UUID | None = None,
    name: str = "",
) -> ServerSummary:
    row = await fetch_one(
        f"""
        INSERT INTO infra_servers (name, type, host, port, username, password, certificate_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING {_COLS}
        """,
        name, server_type, host, port, username,
        crypto_service.encrypt(password),
        certificate_id,
    )
    assert row is not None
    _log.info("infra_servers.create", host=host, type=server_type)
    return _to_summary(row)


async def update(server_id: UUID, **kwargs: Any) -> ServerSummary:
    await get_by_id(server_id)

    updates: dict[str, Any] = {}
    for field in ("name", "host", "port", "username", "password", "certificate_id"):
        if field in kwargs and kwargs[field] is not None:
            val = kwargs[field]
            if field == "password":
                val = crypto_service.encrypt(val)
            updates[field] = val

    if not updates:
        return await get_by_id(server_id)

    sets = [f"{k} = ${i}" for i, k in enumerate(updates, 2)]
    row = await fetch_one(
        f"UPDATE infra_servers SET {', '.join(sets)} WHERE id = $1 RETURNING {_COLS}",
        server_id, *updates.values(),
    )
    assert row is not None
    _log.info("infra_servers.update", id=str(server_id))
    return _to_summary(row)


async def delete(server_id: UUID) -> None:
    row = await fetch_one(
        "DELETE FROM infra_servers WHERE id = $1 RETURNING id", server_id,
    )
    if row is None:
        raise ServerNotFoundError(f"Server {server_id} not found")
    _log.info("infra_servers.delete", id=str(server_id))
