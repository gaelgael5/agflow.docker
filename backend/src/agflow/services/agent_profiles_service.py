"""Agent profiles — stored in agent.json on disk."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from agflow.schemas.agents import AgentProfileSummary
from agflow.services import agent_files_service

_log = structlog.get_logger(__name__)

_PROFILE_NS = uuid.UUID("c3d4e5f6-a7b8-9012-cdef-123456789012")


def _profile_id(agent_slug: str, profile_name: str) -> UUID:
    return uuid.uuid5(_PROFILE_NS, f"{agent_slug}:{profile_name}")


class ProfileNotFoundError(Exception):
    pass


class DuplicateProfileError(Exception):
    pass


def _to_summary(slug: str, profile: dict[str, Any]) -> AgentProfileSummary:
    name = profile.get("name", "")
    now = datetime.now(tz=UTC)
    raw_docs = profile.get("documents", [])
    doc_ids: list[UUID] = []
    for d in raw_docs:
        try:
            doc_ids.append(UUID(str(d)))
        except (ValueError, AttributeError):
            pass
    return AgentProfileSummary(
        id=_profile_id(slug, name),
        agent_id=agent_files_service.agent_id_from_slug(slug),
        name=name,
        description=profile.get("description", ""),
        document_ids=doc_ids,
        template_slug=profile.get("template_slug", ""),
        template_culture=profile.get("template_culture", ""),
        created_at=now,
        updated_at=now,
    )


def _find_agent_slug(agent_id: UUID) -> str:
    for slug in agent_files_service.list_agent_slugs():
        if agent_files_service.agent_id_from_slug(slug) == agent_id:
            return slug
    raise ProfileNotFoundError(f"Agent {agent_id} not found")


async def list_for_agent(agent_id: UUID) -> list[AgentProfileSummary]:
    slug = _find_agent_slug(agent_id)
    data = agent_files_service.read_agent(slug)
    return [_to_summary(slug, p) for p in data.get("profiles", [])]


async def get_by_id(profile_id: UUID) -> AgentProfileSummary:
    for slug in agent_files_service.list_agent_slugs():
        data = agent_files_service.read_agent(slug)
        for p in data.get("profiles", []):
            if _profile_id(slug, p.get("name", "")) == profile_id:
                return _to_summary(slug, p)
    raise ProfileNotFoundError(f"Profile {profile_id} not found")


async def create(
    agent_id: UUID,
    name: str,
    description: str = "",
    document_ids: list[UUID] | None = None,
) -> AgentProfileSummary:
    slug = _find_agent_slug(agent_id)
    data = agent_files_service.read_agent(slug)
    profiles = data.get("profiles", [])
    if any(p.get("name") == name for p in profiles):
        raise DuplicateProfileError(f"Profile '{name}' already exists")
    profile = {
        "name": name,
        "description": description,
        "documents": [str(d) for d in (document_ids or [])],
    }
    profiles.append(profile)
    data["profiles"] = profiles
    agent_files_service.write_agent(slug, data)
    _log.info("agent_profiles.create", slug=slug, name=name)
    return _to_summary(slug, profile)


async def update(
    profile_id: UUID,
    name: str | None = None,
    description: str | None = None,
    document_ids: list[UUID] | None = None,
    template_slug: str | None = None,
    template_culture: str | None = None,
) -> AgentProfileSummary:
    for slug in agent_files_service.list_agent_slugs():
        data = agent_files_service.read_agent(slug)
        for i, p in enumerate(data.get("profiles", [])):
            if _profile_id(slug, p.get("name", "")) == profile_id:
                if name is not None:
                    p["name"] = name
                if description is not None:
                    p["description"] = description
                if document_ids is not None:
                    p["documents"] = [str(d) for d in document_ids]
                if template_slug is not None:
                    p["template_slug"] = template_slug
                if template_culture is not None:
                    p["template_culture"] = template_culture
                data["profiles"][i] = p
                agent_files_service.write_agent(slug, data)
                _log.info("agent_profiles.update", profile_id=str(profile_id))
                return _to_summary(slug, p)
    raise ProfileNotFoundError(f"Profile {profile_id} not found")


async def delete(profile_id: UUID) -> None:
    for slug in agent_files_service.list_agent_slugs():
        data = agent_files_service.read_agent(slug)
        profiles = data.get("profiles", [])
        for i, p in enumerate(profiles):
            if _profile_id(slug, p.get("name", "")) == profile_id:
                profiles.pop(i)
                data["profiles"] = profiles
                agent_files_service.write_agent(slug, data)
                _log.info("agent_profiles.delete", profile_id=str(profile_id))
                return
    raise ProfileNotFoundError(f"Profile {profile_id} not found")


async def resolve_documents(
    document_ids: list[UUID],
) -> tuple[list[dict], list[UUID]]:
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
