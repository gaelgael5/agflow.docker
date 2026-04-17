from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import structlog

from agflow.schemas.catalogs import ProbeResult

_log = structlog.get_logger(__name__)
_DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def _headers(api_key: str | None) -> dict[str, str]:
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


@asynccontextmanager
async def _maybe_client(
    client: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.AsyncClient]:
    if client is not None:
        yield client
    else:
        async with httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT, follow_redirects=True
        ) as c:
            yield c


async def probe(
    base_url: str,
    api_key: str | None,
    client: httpx.AsyncClient | None = None,
) -> ProbeResult:
    """Test connectivity to a registry via GET {base_url}/health."""
    url = base_url.rstrip("/") + "/health"
    try:
        async with _maybe_client(client) as c:
            response = await c.get(url, headers=_headers(api_key))
    except httpx.HTTPError as exc:
        _log.warning("discovery.probe.error", error=str(exc))
        return ProbeResult(ok=False, detail=f"Connection error: {exc}")

    if response.status_code == 200:
        return ProbeResult(ok=True, detail=f"HTTP 200 from {url}")
    return ProbeResult(
        ok=False, detail=f"HTTP {response.status_code} — {response.text[:200]}"
    )


async def fetch_targets(
    base_url: str,
    api_key: str | None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Fetch all installation targets from the registry."""
    url = base_url.rstrip("/") + "/targets"
    async with _maybe_client(client) as c:
        response = await c.get(url, headers=_headers(api_key))
    response.raise_for_status()
    return response.json()


# ──────────────────────────────────────────────────────────────────────────
# MCP servers
#
# Real yoops.org API shape (as of 2026-04-11):
#   GET /api/v1/services?search=<query>
#     → {"items": [...], "total": N}
#     item fields: id (UUID), name ("user/repo"), source_url, doc_url,
#                  transport, source_type, category, tags, stars,
#                  canonical_id, is_deprecated, has_summaries
#   GET /api/v1/services/{id}
#     → single item
# ──────────────────────────────────────────────────────────────────────────


def _map_mcp_item(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a yoops /search_mcp item into agflow's MCPSearchItem shape."""
    full_name: str = raw.get("name") or ""
    short_name = full_name.split("/")[-1] if "/" in full_name else full_name
    description: str = raw.get("description") or ""
    short_desc = description[:200] if description else (raw.get("category") or "")
    return {
        "package_id": raw.get("id", ""),
        "name": short_name or full_name,
        "repo": full_name,
        "repo_url": raw.get("source_url") or "",
        "transport": raw.get("transport") or "stdio",
        "category": raw.get("category") or "",
        "short_description": short_desc,
        "long_description": description,
        "documentation_url": raw.get("doc_url") or "",
        "has_summaries": bool(description),
        "recipes": raw.get("recipes") or {},
        "parameters": raw.get("parameters") or [],
    }


async def search_mcp(
    base_url: str,
    api_key: str | None,
    query: str,
    semantic: bool = False,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    url = base_url.rstrip("/") + "/search_mcp"
    params: dict[str, Any] = {"per_page": 50}
    if query:
        params["q"] = query
    if semantic:
        params["semantic"] = True
    async with _maybe_client(client) as c:
        response = await c.get(url, headers=_headers(api_key), params=params)
    response.raise_for_status()
    data = response.json()
    items = data.get("items", []) if isinstance(data, dict) else data
    return [_map_mcp_item(item) for item in items]


async def get_mcp_detail(
    base_url: str,
    api_key: str | None,
    package_id: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + f"/services/{package_id}"
    async with _maybe_client(client) as c:
        response = await c.get(url, headers=_headers(api_key))
    response.raise_for_status()
    return _map_mcp_item(response.json())


async def get_service_summary(
    base_url: str,
    api_key: str | None,
    service_id: str | int,
    culture: str = "en",
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Fetch the summary for a service in the given language (culture).

    Returns the summary markdown text, or None if no summary exists
    for that service/culture combination.
    """
    url = base_url.rstrip("/") + "/summaries"
    params = {"service_id": service_id, "culture": culture}
    async with _maybe_client(client) as c:
        response = await c.get(url, headers=_headers(api_key), params=params)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    items = data.get("items", []) if isinstance(data, dict) else data
    if not items:
        return None
    return items[0].get("summary", "")


# ──────────────────────────────────────────────────────────────────────────
# Skills
#
# Real yoops.org API shape:
#   GET /api/v1/skills?offset=&limit=
#     → raw array (no wrapper), item fields:
#       id, name, description, target_type, source_url, licence,
#       category, install_command, weekly_installs, has_summary, ...
#   No server-side search filter — we fetch up to `limit` and filter
#   client-side when a query is provided.
#   GET /api/v1/skills/{id}
#     → single item
# ──────────────────────────────────────────────────────────────────────────


def _map_skill_item(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a yoops /search_skills item into agflow's SkillSearchItem shape."""
    return {
        "skill_id": raw.get("id", ""),
        "name": raw.get("name") or "",
        "description": raw.get("description") or "",
        "source_url": raw.get("source_url") or "",
    }


async def search_skills(
    base_url: str,
    api_key: str | None,
    query: str,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    url = base_url.rstrip("/") + "/search_skills"
    params: dict[str, Any] = {"per_page": 50}
    if query:
        params["q"] = query
    async with _maybe_client(client) as c:
        response = await c.get(url, headers=_headers(api_key), params=params)
    response.raise_for_status()
    data = response.json()
    items = data.get("items", []) if isinstance(data, dict) else data
    return [_map_skill_item(item) for item in items]


async def get_skill_detail(
    base_url: str,
    api_key: str | None,
    skill_id: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + f"/skills/{skill_id}"
    async with _maybe_client(client) as c:
        response = await c.get(url, headers=_headers(api_key))
    response.raise_for_status()
    raw = response.json()
    # Descriptive fields only — the registry doesn't expose a readme/content,
    # so `content_md` falls back to the description for display purposes.
    return {
        "skill_id": raw.get("id", ""),
        "name": raw.get("name") or "",
        "description": raw.get("description") or "",
        "content_md": raw.get("description") or "",
    }
