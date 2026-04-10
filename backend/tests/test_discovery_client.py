from __future__ import annotations

import os

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET", "x")
os.environ.setdefault("ADMIN_EMAIL", "a@b.c")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "x")
os.environ.setdefault("SECRETS_MASTER_KEY", "x")

from agflow.services import discovery_client  # noqa: E402


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_probe_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/health")
        assert request.headers.get("Authorization") == "Bearer test-key"
        return httpx.Response(200, json={"status": "ok"})

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
        result = await discovery_client.probe(
            "https://api.example.com", "test-key", client=c
        )
    assert result.ok is True
    assert "200" in result.detail


@pytest.mark.asyncio
async def test_probe_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized")

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
        result = await discovery_client.probe(
            "https://api.example.com", "bad-key", client=c
        )
    assert result.ok is False
    assert "401" in result.detail


@pytest.mark.asyncio
async def test_search_mcp_returns_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/mcp/search")
        assert request.url.params.get("q") == "filesystem"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "package_id": "@mcp/fs",
                        "name": "Filesystem",
                        "repo": "modelcontextprotocol/servers",
                        "repo_url": "https://github.com/modelcontextprotocol/servers",
                        "transport": "stdio",
                        "short_description": "Access local files",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
        items = await discovery_client.search_mcp(
            "https://api.example.com", "k", "filesystem", semantic=False, client=c
        )
    assert len(items) == 1
    assert items[0]["package_id"] == "@mcp/fs"


@pytest.mark.asyncio
async def test_get_mcp_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "mcp/" in str(request.url)
        return httpx.Response(
            200,
            json={
                "package_id": "@mcp/fs",
                "name": "Filesystem",
                "repo": "modelcontextprotocol/servers",
                "transport": "stdio",
                "parameters_schema": [
                    {"name": "ROOT_PATH", "required": True}
                ],
            },
        )

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
        detail = await discovery_client.get_mcp_detail(
            "https://api.example.com", "k", "@mcp/fs", client=c
        )
    assert detail["package_id"] == "@mcp/fs"
    assert detail["parameters_schema"][0]["name"] == "ROOT_PATH"


@pytest.mark.asyncio
async def test_search_skills() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/skills/search")
        return httpx.Response(
            200, json={"items": [{"skill_id": "md", "name": "Markdown"}]}
        )

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
        items = await discovery_client.search_skills(
            "https://api.example.com", "k", "markdown", client=c
        )
    assert items[0]["skill_id"] == "md"


@pytest.mark.asyncio
async def test_get_skill_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "skill_id": "md",
                "name": "Markdown",
                "description": "md skill",
                "content_md": "# SKILL.md",
            },
        )

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
        detail = await discovery_client.get_skill_detail(
            "https://api.example.com", "k", "md", client=c
        )
    assert detail["content_md"].startswith("# SKILL")
