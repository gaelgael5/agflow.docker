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
    """Real yoops.org API: GET /services?search=... returns {items,total}.
    Each item has id, name (user/repo), source_url, doc_url, transport, etc.
    Client maps those to MCPSearchItem shape."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/services")
        assert request.url.params.get("search") == "filesystem"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "aa111111-1111-1111-1111-111111111111",
                        "name": "modelcontextprotocol/servers",
                        "source_url": "https://github.com/modelcontextprotocol/servers",
                        "doc_url": "https://glama.ai/mcp/servers/fs",
                        "transport": "stdio",
                        "tags": ["files", "io"],
                        "category": "filesystem",
                    }
                ],
                "total": 1,
            },
        )

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
        items = await discovery_client.search_mcp(
            "https://api.example.com", "k", "filesystem", semantic=False, client=c
        )
    assert len(items) == 1
    item = items[0]
    assert item["package_id"] == "aa111111-1111-1111-1111-111111111111"
    assert item["name"] == "servers"  # short name after slash split
    assert item["repo"] == "modelcontextprotocol/servers"
    assert item["repo_url"] == "https://github.com/modelcontextprotocol/servers"
    assert item["transport"] == "stdio"
    assert "filesystem" in item["short_description"]


@pytest.mark.asyncio
async def test_get_mcp_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/services/" in str(request.url)
        return httpx.Response(
            200,
            json={
                "id": "bb222222-2222-2222-2222-222222222222",
                "name": "modelcontextprotocol/servers",
                "source_url": "https://github.com/modelcontextprotocol/servers",
                "doc_url": "",
                "transport": "stdio",
                "tags": [],
                "category": None,
            },
        )

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
        detail = await discovery_client.get_mcp_detail(
            "https://api.example.com",
            "k",
            "bb222222-2222-2222-2222-222222222222",
            client=c,
        )
    assert detail["package_id"] == "bb222222-2222-2222-2222-222222222222"
    assert detail["repo"] == "modelcontextprotocol/servers"
    assert detail["transport"] == "stdio"


@pytest.mark.asyncio
async def test_search_skills_filters_client_side() -> None:
    """Real yoops.org API returns a raw array with no server-side filter,
    so the client fetches and filters locally by matching the query."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/skills")
        return httpx.Response(
            200,
            json=[
                {
                    "id": "cc111111-1111-1111-1111-111111111111",
                    "name": "Markdown editor",
                    "description": "Edit markdown files with style",
                    "target_type": "claude",
                    "source_url": "https://github.com/x/y",
                },
                {
                    "id": "cc222222-2222-2222-2222-222222222222",
                    "name": "Python helper",
                    "description": "Python snippets",
                    "target_type": "claude",
                    "source_url": "https://github.com/a/b",
                },
            ],
        )

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
        items = await discovery_client.search_skills(
            "https://api.example.com", "k", "markdown", client=c
        )
    assert len(items) == 1
    assert items[0]["name"] == "Markdown editor"
    assert items[0]["skill_id"] == "cc111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_get_skill_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "dd111111-1111-1111-1111-111111111111",
                "name": "Markdown",
                "description": "md skill — guidelines for markdown editing",
                "target_type": "claude",
                "source_url": "",
            },
        )

    async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
        detail = await discovery_client.get_skill_detail(
            "https://api.example.com",
            "k",
            "dd111111-1111-1111-1111-111111111111",
            client=c,
        )
    assert detail["skill_id"] == "dd111111-1111-1111-1111-111111111111"
    assert detail["name"] == "Markdown"
    # Real registry has no readme — content_md falls back to description.
    assert detail["content_md"] == detail["description"]
