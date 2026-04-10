from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.82:5432/agflow"
os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")

from agflow.db.migrations import run_migrations  # noqa: E402
from agflow.db.pool import close_pool, execute  # noqa: E402
from agflow.services import (  # noqa: E402
    discovery_services_service,
    mcp_catalog_service,
    skills_catalog_service,
)

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture(autouse=True)
async def _clean():
    for t in [
        "skills",
        "mcp_servers",
        "discovery_services",
        "dockerfile_builds",
        "dockerfile_files",
        "dockerfiles",
        "role_documents",
        "roles",
        "secrets",
        "schema_migrations",
    ]:
        await execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    await run_migrations(_MIGRATIONS_DIR)
    await discovery_services_service.create(
        service_id="yoops", name="yoops", base_url="https://x"
    )
    yield
    await close_pool()


_MCP_DETAIL = {
    "package_id": "@mcp/fs",
    "name": "Filesystem",
    "repo": "modelcontextprotocol/servers",
    "repo_url": "https://github.com/modelcontextprotocol/servers",
    "transport": "stdio",
    "short_description": "Local files",
    "parameters_schema": [{"name": "ROOT_PATH", "required": True}],
}

_SKILL_DETAIL = {
    "skill_id": "md",
    "name": "Markdown",
    "description": "Markdown editing",
    "content_md": "# SKILL.md",
}


@pytest.mark.asyncio
async def test_install_mcp_persists_detail() -> None:
    with patch(
        "agflow.services.mcp_catalog_service.discovery_client.get_mcp_detail",
        new=AsyncMock(return_value=_MCP_DETAIL),
    ):
        installed = await mcp_catalog_service.install("yoops", "@mcp/fs")

    assert installed.package_id == "@mcp/fs"
    assert installed.name == "Filesystem"
    assert installed.transport == "stdio"
    assert installed.parameters_schema == [{"name": "ROOT_PATH", "required": True}]


@pytest.mark.asyncio
async def test_install_mcp_duplicate_raises() -> None:
    with patch(
        "agflow.services.mcp_catalog_service.discovery_client.get_mcp_detail",
        new=AsyncMock(return_value=_MCP_DETAIL),
    ):
        await mcp_catalog_service.install("yoops", "@mcp/fs")
        with pytest.raises(mcp_catalog_service.DuplicateMCPServerError):
            await mcp_catalog_service.install("yoops", "@mcp/fs")


@pytest.mark.asyncio
async def test_update_parameters() -> None:
    with patch(
        "agflow.services.mcp_catalog_service.discovery_client.get_mcp_detail",
        new=AsyncMock(return_value=_MCP_DETAIL),
    ):
        installed = await mcp_catalog_service.install("yoops", "@mcp/fs")

    updated = await mcp_catalog_service.update_parameters(
        installed.id, {"ROOT_PATH": "/workspace"}
    )
    assert updated.parameters == {"ROOT_PATH": "/workspace"}


@pytest.mark.asyncio
async def test_delete_mcp() -> None:
    with patch(
        "agflow.services.mcp_catalog_service.discovery_client.get_mcp_detail",
        new=AsyncMock(return_value=_MCP_DETAIL),
    ):
        installed = await mcp_catalog_service.install("yoops", "@mcp/fs")

    await mcp_catalog_service.delete(installed.id)

    with pytest.raises(mcp_catalog_service.MCPServerNotFoundError):
        await mcp_catalog_service.get_by_id(installed.id)


@pytest.mark.asyncio
async def test_list_mcp_sorted_by_repo() -> None:
    with patch(
        "agflow.services.mcp_catalog_service.discovery_client.get_mcp_detail",
        new=AsyncMock(return_value=_MCP_DETAIL),
    ):
        await mcp_catalog_service.install("yoops", "@mcp/fs")

    items = await mcp_catalog_service.list_all()
    assert len(items) == 1
    assert items[0].repo == "modelcontextprotocol/servers"


@pytest.mark.asyncio
async def test_install_skill() -> None:
    with patch(
        "agflow.services.skills_catalog_service.discovery_client.get_skill_detail",
        new=AsyncMock(return_value=_SKILL_DETAIL),
    ):
        installed = await skills_catalog_service.install("yoops", "md")

    assert installed.name == "Markdown"
    assert installed.content_md == "# SKILL.md"


@pytest.mark.asyncio
async def test_delete_skill() -> None:
    with patch(
        "agflow.services.skills_catalog_service.discovery_client.get_skill_detail",
        new=AsyncMock(return_value=_SKILL_DETAIL),
    ):
        installed = await skills_catalog_service.install("yoops", "md")

    await skills_catalog_service.delete(installed.id)

    with pytest.raises(skills_catalog_service.SkillNotFoundError):
        await skills_catalog_service.get_by_id(installed.id)
