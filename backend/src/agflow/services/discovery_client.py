from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
import structlog

from agflow.schemas.catalogs import ProbeResult

_log = structlog.get_logger(__name__)
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


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
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as c:
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


async def search_mcp(
    base_url: str,
    api_key: str | None,
    query: str,
    semantic: bool = False,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    url = base_url.rstrip("/") + "/mcp/search"
    params = {"q": query, "semantic": "1" if semantic else "0"}
    async with _maybe_client(client) as c:
        response = await c.get(url, headers=_headers(api_key), params=params)
    response.raise_for_status()
    data = response.json()
    return data.get("items", [])


async def get_mcp_detail(
    base_url: str,
    api_key: str | None,
    package_id: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    # package_id can contain special chars (ex: @scope/name) — pass as path segment
    url = base_url.rstrip("/") + f"/mcp/{package_id}"
    async with _maybe_client(client) as c:
        response = await c.get(url, headers=_headers(api_key))
    response.raise_for_status()
    return response.json()


async def search_skills(
    base_url: str,
    api_key: str | None,
    query: str,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    url = base_url.rstrip("/") + "/skills/search"
    async with _maybe_client(client) as c:
        response = await c.get(
            url, headers=_headers(api_key), params={"q": query}
        )
    response.raise_for_status()
    data = response.json()
    return data.get("items", [])


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
    return response.json()
