from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.agents import AgentProfileSummary

_log = structlog.get_logger(__name__)

_COLS = (
    "id, agent_id, name, description, document_ids, created_at, updated_at"
)


class ProfileNotFoundError(Exception):
    pass


class DuplicateProfileError(Exception):
    pass


def _row(row: dict) -> AgentProfileSummary:
    return AgentProfileSummary(**row)


async def list_for_agent(agent_id: UUID) -> list[AgentProfileSummary]:
    rows = await fetch_all(
        f"""
        SELECT {_COLS}
        FROM agent_profiles
        WHERE agent_id = $1
        ORDER BY name ASC
        """,
        agent_id,
    )
    return [_row(r) for r in rows]


async def get_by_id(profile_id: UUID) -> AgentProfileSummary:
    row = await fetch_one(
        f"SELECT {_COLS} FROM agent_profiles WHERE id = $1", profile_id
    )
    if row is None:
        raise ProfileNotFoundError(f"Profile {profile_id} not found")
    return _row(row)


async def create(
    agent_id: UUID,
    name: str,
    description: str = "",
    document_ids: list[UUID] | None = None,
) -> AgentProfileSummary:
    try:
        row = await fetch_one(
            f"""
            INSERT INTO agent_profiles (agent_id, name, description, document_ids)
            VALUES ($1, $2, $3, $4::uuid[])
            RETURNING {_COLS}
            """,
            agent_id,
            name,
            description,
            document_ids or [],
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateProfileError(
            f"Profile '{name}' already exists for agent {agent_id}"
        ) from exc
    assert row is not None
    _log.info("agent_profiles.create", agent_id=str(agent_id), name=name)
    return _row(row)


async def update(
    profile_id: UUID,
    name: str | None = None,
    description: str | None = None,
    document_ids: list[UUID] | None = None,
) -> AgentProfileSummary:
    sets: list[str] = []
    args: list = []
    idx = 1
    if name is not None:
        sets.append(f"name = ${idx}")
        args.append(name)
        idx += 1
    if description is not None:
        sets.append(f"description = ${idx}")
        args.append(description)
        idx += 1
    if document_ids is not None:
        sets.append(f"document_ids = ${idx}::uuid[]")
        args.append(document_ids)
        idx += 1
    if not sets:
        return await get_by_id(profile_id)
    sets.append("updated_at = NOW()")
    args.append(profile_id)
    try:
        row = await fetch_one(
            f"""
            UPDATE agent_profiles SET {", ".join(sets)}
            WHERE id = ${idx}
            RETURNING {_COLS}
            """,
            *args,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateProfileError(str(exc)) from exc
    if row is None:
        raise ProfileNotFoundError(f"Profile {profile_id} not found")
    _log.info("agent_profiles.update", profile_id=str(profile_id))
    return _row(row)


async def delete(profile_id: UUID) -> None:
    result = await execute(
        "DELETE FROM agent_profiles WHERE id = $1", profile_id
    )
    if result == "DELETE 0":
        raise ProfileNotFoundError(f"Profile {profile_id} not found")
    _log.info("agent_profiles.delete", profile_id=str(profile_id))


async def resolve_documents(
    document_ids: list[UUID],
) -> tuple[list[dict], list[UUID]]:
    """Resolve a list of document UUIDs against `role_documents`.

    Returns a tuple of (found rows, missing ids). Missing ids signal that
    the profile references deleted documents or documents from an ex-role
    of the agent — the caller should surface these as validation errors
    and flag the agent as in-error.
    """
    if not document_ids:
        return [], []
    rows = await fetch_all(
        """
        SELECT id, role_id, section, name, content_md, parent_path, protected,
               created_at, updated_at
        FROM role_documents
        WHERE id = ANY($1::uuid[])
        """,
        document_ids,
    )
    found_ids = {r["id"] for r in rows}
    missing = [uid for uid in document_ids if uid not in found_ids]
    return list(rows), missing
