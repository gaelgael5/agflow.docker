from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agflow.db.migrations import run_migrations
from agflow.db.pool import close_pool, execute
from agflow.main import create_app
from agflow.schemas.catalogs import ProbeResult

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
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

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    await close_pool()


async def _token(c: AsyncClient) -> dict[str, str]:
    res = await c.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.asyncio
async def test_discovery_services_crud(client: AsyncClient) -> None:
    h = await _token(client)

    create = await client.post(
        "/api/admin/discovery-services",
        headers=h,
        json={"id": "yoops", "name": "yoops.org", "base_url": "https://mcp.yoops.org"},
    )
    assert create.status_code == 201
    assert create.json()["id"] == "yoops"

    listing = await client.get("/api/admin/discovery-services", headers=h)
    assert listing.status_code == 200
    assert any(d["id"] == "yoops" for d in listing.json())

    delres = await client.delete("/api/admin/discovery-services/yoops", headers=h)
    assert delres.status_code == 204


@pytest.mark.asyncio
async def test_discovery_test_endpoint_mocked(client: AsyncClient) -> None:
    h = await _token(client)
    await client.post(
        "/api/admin/discovery-services",
        headers=h,
        json={"id": "yoops", "name": "y", "base_url": "https://x"},
    )

    with patch(
        "agflow.services.discovery_services_service.discovery_client.probe",
        new=AsyncMock(return_value=ProbeResult(ok=True, detail="OK")),
    ):
        res = await client.post(
            "/api/admin/discovery-services/yoops/test", headers=h
        )
    assert res.status_code == 200
    assert res.json()["ok"] is True


@pytest.mark.asyncio
async def test_mcp_catalog_install_via_mocked_detail(client: AsyncClient) -> None:
    h = await _token(client)
    await client.post(
        "/api/admin/discovery-services",
        headers=h,
        json={"id": "yoops", "name": "y", "base_url": "https://x"},
    )

    with patch(
        "agflow.services.mcp_catalog_service.discovery_client.get_mcp_detail",
        new=AsyncMock(
            return_value={
                "package_id": "@mcp/fs",
                "name": "Filesystem",
                "repo": "modelcontextprotocol/servers",
                "transport": "stdio",
            }
        ),
    ):
        install = await client.post(
            "/api/admin/mcp-catalog",
            headers=h,
            json={"discovery_service_id": "yoops", "package_id": "@mcp/fs"},
        )
    assert install.status_code == 201
    assert install.json()["name"] == "Filesystem"

    listing = await client.get("/api/admin/mcp-catalog", headers=h)
    assert len(listing.json()) == 1


@pytest.mark.asyncio
async def test_skills_catalog_install_via_mocked_detail(client: AsyncClient) -> None:
    h = await _token(client)
    await client.post(
        "/api/admin/discovery-services",
        headers=h,
        json={"id": "yoops", "name": "y", "base_url": "https://x"},
    )

    with patch(
        "agflow.services.skills_catalog_service.discovery_client.get_skill_detail",
        new=AsyncMock(
            return_value={
                "skill_id": "md",
                "name": "Markdown",
                "description": "md skill",
                "content_md": "# SKILL.md",
            }
        ),
    ):
        install = await client.post(
            "/api/admin/skills-catalog",
            headers=h,
            json={"discovery_service_id": "yoops", "skill_id": "md"},
        )
    assert install.status_code == 201
    assert install.json()["content_md"].startswith("# SKILL")


@pytest.mark.asyncio
async def test_search_mcp_mocked(client: AsyncClient) -> None:
    h = await _token(client)
    await client.post(
        "/api/admin/discovery-services",
        headers=h,
        json={"id": "yoops", "name": "y", "base_url": "https://x"},
    )

    with patch(
        "agflow.api.admin.discovery_services.discovery_client.search_mcp",
        new=AsyncMock(
            return_value=[
                {
                    "package_id": "@mcp/fs",
                    "name": "Filesystem",
                    "repo": "modelcontextprotocol/servers",
                    "transport": "stdio",
                }
            ]
        ),
    ):
        res = await client.get(
            "/api/admin/discovery-services/yoops/search/mcp?q=filesystem",
            headers=h,
        )
    assert res.status_code == 200
    assert len(res.json()) == 1
