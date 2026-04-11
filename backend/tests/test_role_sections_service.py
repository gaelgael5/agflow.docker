from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agflow.db.migrations import run_migrations
from agflow.db.pool import close_pool, execute
from agflow.services import (
    role_documents_service,
    role_sections_service,
    roles_service,
)

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture
async def db() -> AsyncIterator[None]:
    for t in [
        "agent_skills",
        "agent_mcp_servers",
        "agents",
        "skills",
        "mcp_servers",
        "discovery_services",
        "dockerfile_builds",
        "dockerfile_files",
        "dockerfiles",
        "role_documents",
        "role_sections",
        "roles",
        "secrets",
        "schema_migrations",
    ]:
        await execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    await run_migrations(_MIGRATIONS_DIR)
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_role_auto_seeds_natives(db: None) -> None:
    await roles_service.create(role_id="analyst", display_name="Analyst")
    sections = await role_sections_service.list_for_role("analyst")
    names = [s.name for s in sections]
    assert names == ["roles", "missions", "competences"]
    assert all(s.is_native for s in sections)
    assert [s.display_name for s in sections] == ["Rôles", "Missions", "Compétences"]


@pytest.mark.asyncio
async def test_create_custom_section(db: None) -> None:
    await roles_service.create(role_id="dev", display_name="Dev")
    section = await role_sections_service.create(
        role_id="dev", name="outils", display_name="Outils"
    )
    assert section.name == "outils"
    assert section.is_native is False
    assert section.position == 3  # after 3 natives

    all_sections = await role_sections_service.list_for_role("dev")
    assert [s.name for s in all_sections] == ["roles", "missions", "competences", "outils"]


@pytest.mark.asyncio
async def test_create_duplicate_section(db: None) -> None:
    await roles_service.create(role_id="dev", display_name="Dev")
    with pytest.raises(role_sections_service.DuplicateSectionError):
        await role_sections_service.create(
            role_id="dev", name="roles", display_name="Roles"
        )


@pytest.mark.asyncio
async def test_delete_native_is_forbidden(db: None) -> None:
    await roles_service.create(role_id="dev", display_name="Dev")
    with pytest.raises(role_sections_service.ProtectedSectionError):
        await role_sections_service.delete("dev", "roles")


@pytest.mark.asyncio
async def test_delete_empty_custom_section(db: None) -> None:
    await roles_service.create(role_id="dev", display_name="Dev")
    await role_sections_service.create(
        role_id="dev", name="outils", display_name="Outils"
    )
    await role_sections_service.delete("dev", "outils")
    sections = await role_sections_service.list_for_role("dev")
    assert "outils" not in [s.name for s in sections]


@pytest.mark.asyncio
async def test_delete_non_empty_section_blocked(db: None) -> None:
    await roles_service.create(role_id="dev", display_name="Dev")
    await role_sections_service.create(
        role_id="dev", name="outils", display_name="Outils"
    )
    await role_documents_service.create(
        role_id="dev", section="outils", name="vim", content_md="# vim"
    )
    with pytest.raises(role_sections_service.SectionNotEmptyError):
        await role_sections_service.delete("dev", "outils")


@pytest.mark.asyncio
async def test_document_in_unknown_section_fails(db: None) -> None:
    """FK constraint should reject documents targeting a non-existent section."""
    import asyncpg

    await roles_service.create(role_id="dev", display_name="Dev")
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await role_documents_service.create(
            role_id="dev",
            section="unknown_section",
            name="ghost",
            content_md="",
        )
