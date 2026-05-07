from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.agents import AgentProfileSummary

_log = structlog.get_logger(__name__)

_COLS = (
    "ap.id, a.id AS agent_id, ap.agent_slug, ap.name, ap.description, "
    "ap.document_ids, ap.template_slug, ap.template_culture, ap.output_dir, "
    "ap.created_at, ap.updated_at"
)

_JOIN = "FROM agent_profiles ap JOIN agents a ON a.slug = ap.agent_slug"


class ProfileNotFoundError(Exception):
    pass


class DuplicateProfileError(Exception):
    pass


def _row(row: dict) -> AgentProfileSummary:
    return AgentProfileSummary(
        id=row["id"],
        agent_id=row["agent_id"],
        name=row["name"],
        description=row["description"],
        document_ids=list(row["document_ids"] or []),
        template_slug=row["template_slug"],
        template_culture=row["template_culture"],
        output_dir=row["output_dir"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_for_agent(agent_id: UUID) -> list[AgentProfileSummary]:
    rows = await fetch_all(
        f"SELECT {_COLS} {_JOIN} WHERE a.id = $1 ORDER BY ap.name ASC",
        agent_id,
    )
    return [_row(r) for r in rows]


async def get_by_id(profile_id: UUID) -> AgentProfileSummary:
    row = await fetch_one(
        f"SELECT {_COLS} {_JOIN} WHERE ap.id = $1",
        profile_id,
    )
    if row is None:
        raise ProfileNotFoundError(f"Profile {profile_id} not found")
    return _row(row)


async def create(
    agent_id: UUID,
    name: str,
    description: str = "",
    document_ids: list[UUID] | None = None,
    template_slug: str = "",
    template_culture: str = "",
    output_dir: str = "workspace/docs/missions",
) -> AgentProfileSummary:
    slug_row = await fetch_one("SELECT slug FROM agents WHERE id = $1", agent_id)
    if slug_row is None:
        raise ProfileNotFoundError(f"Agent {agent_id} not found")
    agent_slug = slug_row["slug"]
    doc_ids: list[UUID] = document_ids or []
    try:
        row = await fetch_one(
            """
            INSERT INTO agent_profiles (agent_slug, name, description, document_ids,
                template_slug, template_culture, output_dir)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id, $8::uuid AS agent_id, agent_slug, name, description,
                document_ids, template_slug, template_culture, output_dir,
                created_at, updated_at
            """,
            agent_slug, name, description, doc_ids,
            template_slug, template_culture, output_dir,
            agent_id,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateProfileError(
            f"Profile '{name}' already exists for this agent"
        ) from exc
    assert row is not None
    _log.info("agent_profiles.create", agent_slug=agent_slug, name=name)
    return _row(row)


async def update(
    profile_id: UUID,
    name: str | None = None,
    description: str | None = None,
    document_ids: list[UUID] | None = None,
    template_slug: str | None = None,
    template_culture: str | None = None,
    output_dir: str | None = None,
) -> AgentProfileSummary:
    sets: list[str] = []
    params: list = [profile_id]
    if name is not None:
        params.append(name)
        sets.append(f"name = ${len(params)}")
    if description is not None:
        params.append(description)
        sets.append(f"description = ${len(params)}")
    if document_ids is not None:
        params.append(document_ids)
        sets.append(f"document_ids = ${len(params)}")
    if template_slug is not None:
        params.append(template_slug)
        sets.append(f"template_slug = ${len(params)}")
    if template_culture is not None:
        params.append(template_culture)
        sets.append(f"template_culture = ${len(params)}")
    if output_dir is not None:
        params.append(output_dir)
        sets.append(f"output_dir = ${len(params)}")
    if not sets:
        return await get_by_id(profile_id)
    set_clause = ", ".join(sets)
    row = await fetch_one(
        f"""
        UPDATE agent_profiles SET {set_clause}
        WHERE id = $1
        RETURNING id, agent_slug, name, description, document_ids,
            template_slug, template_culture, output_dir, created_at, updated_at
        """,
        *params,
    )
    if row is None:
        raise ProfileNotFoundError(f"Profile {profile_id} not found")
    agent_row = await fetch_one("SELECT id FROM agents WHERE slug = $1", row["agent_slug"])
    return _row({**dict(row), "agent_id": agent_row["id"] if agent_row else None})


async def delete(profile_id: UUID) -> None:
    result = await execute("DELETE FROM agent_profiles WHERE id = $1", profile_id)
    if result == "DELETE 0":
        raise ProfileNotFoundError(f"Profile {profile_id} not found")
    _log.info("agent_profiles.delete", profile_id=str(profile_id))


async def resolve_documents(document_ids: list[UUID]) -> tuple[list[dict], list[UUID]]:
    if not document_ids:
        return [], []
    from agflow.services import role_documents_service

    found = []
    missing = []
    for uid in document_ids:
        try:
            doc = await role_documents_service.get_by_id(uid)
            found.append({
                "id": doc.id,
                "role_id": doc.role_id,
                "section": doc.section,
                "name": doc.name,
                "content_md": doc.content_md,
                "parent_path": doc.parent_path,
                "protected": doc.protected,
                "created_at": doc.created_at,
                "updated_at": doc.updated_at,
            })
        except Exception:
            missing.append(uid)
    return found, missing
