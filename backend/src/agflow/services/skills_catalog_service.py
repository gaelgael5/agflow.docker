from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.catalogs import SkillSummary
from agflow.services import discovery_client, discovery_services_service

_log = structlog.get_logger(__name__)

_COLS = (
    "id, discovery_service_id, skill_id, name, description, content_md, "
    "created_at, updated_at"
)


class SkillNotFoundError(Exception):
    pass


class DuplicateSkillError(Exception):
    pass


def _row(row: dict[str, Any]) -> SkillSummary:
    return SkillSummary(**row)


async def list_all() -> list[SkillSummary]:
    rows = await fetch_all(f"SELECT {_COLS} FROM skills ORDER BY name ASC")
    return [_row(r) for r in rows]


async def get_by_id(skill_uuid: UUID) -> SkillSummary:
    row = await fetch_one(f"SELECT {_COLS} FROM skills WHERE id = $1", skill_uuid)
    if row is None:
        raise SkillNotFoundError(f"Skill {skill_uuid} not found")
    return _row(row)


async def install(discovery_service_id: str, skill_id: str) -> SkillSummary:
    service = await discovery_services_service.get_by_id(discovery_service_id)
    api_key = await discovery_services_service._resolve_api_key(service.api_key_var)

    detail = await discovery_client.get_skill_detail(
        service.base_url, api_key, skill_id
    )

    try:
        row = await fetch_one(
            f"""
            INSERT INTO skills (
                discovery_service_id, skill_id, name, description, content_md
            )
            VALUES ($1, $2, $3, $4, $5)
            RETURNING {_COLS}
            """,
            discovery_service_id,
            skill_id,
            detail.get("name", skill_id),
            detail.get("description", ""),
            detail.get("content_md", ""),
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateSkillError(
            f"Skill '{skill_id}' already installed from '{discovery_service_id}'"
        ) from exc
    assert row is not None
    _log.info(
        "skills_catalog.install",
        discovery_service_id=discovery_service_id,
        skill_id=skill_id,
    )
    return _row(row)


async def delete(skill_uuid: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM skills WHERE id = $1", skill_uuid
        )
    if result == "DELETE 0":
        raise SkillNotFoundError(f"Skill {skill_uuid} not found")
    _log.info("skills_catalog.delete", skill_uuid=str(skill_uuid))
