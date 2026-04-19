from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.catalogs import MCPServerSummary
from agflow.services import discovery_client, discovery_services_service

_log = structlog.get_logger(__name__)

_COLS = (
    "id, discovery_service_id, package_id, name, repo, repo_url, transport, "
    "short_description, long_description, documentation_url, parameters, "
    "parameters_schema, recipes, category, created_at, updated_at"
)


class MCPServerNotFoundError(Exception):
    pass


class DuplicateMCPServerError(Exception):
    pass


def _parse_json(raw: Any, default: Any) -> Any:
    if isinstance(raw, str):
        return json.loads(raw) if raw else default
    return raw if raw is not None else default


def _row(row: dict[str, Any]) -> MCPServerSummary:
    return MCPServerSummary(
        id=row["id"],
        discovery_service_id=row["discovery_service_id"],
        package_id=row["package_id"],
        name=row["name"],
        repo=row["repo"],
        repo_url=row["repo_url"],
        transport=row["transport"],
        short_description=row["short_description"],
        long_description=row["long_description"],
        documentation_url=row["documentation_url"],
        parameters=_parse_json(row["parameters"], []),
        parameters_schema=_parse_json(row["parameters_schema"], []),
        recipes=_parse_json(row["recipes"], {}),
        category=row.get("category", ""),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_all() -> list[MCPServerSummary]:
    rows = await fetch_all(
        f"SELECT {_COLS} FROM mcp_servers ORDER BY repo ASC, name ASC"
    )
    return [_row(r) for r in rows]


async def get_by_id(mcp_id: UUID) -> MCPServerSummary:
    row = await fetch_one(
        f"SELECT {_COLS} FROM mcp_servers WHERE id = $1", mcp_id
    )
    if row is None:
        raise MCPServerNotFoundError(f"MCP server {mcp_id} not found")
    return _row(row)


async def install(
    discovery_service_id: str,
    package_id: str,
    recipes: dict | None = None,
    parameters: list | None = None,
    category: str = "",
) -> MCPServerSummary:
    """Fetch details from the registry and insert into the local catalog."""
    service = await discovery_services_service.get_by_id(discovery_service_id)
    api_key = await discovery_services_service._resolve_api_key(service.api_key_var)

    detail = await discovery_client.get_mcp_detail(
        service.base_url, api_key, package_id
    )

    try:
        row = await fetch_one(
            f"""
            INSERT INTO mcp_servers (
                discovery_service_id, package_id, name, repo, repo_url,
                transport, short_description, long_description,
                documentation_url, parameters_schema, recipes, parameters, category
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11::jsonb, $12::jsonb, $13)
            RETURNING {_COLS}
            """,
            discovery_service_id,
            package_id,
            detail.get("name", package_id),
            detail.get("repo", ""),
            detail.get("repo_url", ""),
            detail.get("transport", "stdio"),
            detail.get("short_description", ""),
            detail.get("long_description", ""),
            detail.get("documentation_url", ""),
            json.dumps(detail.get("parameters_schema", [])),
            json.dumps(recipes or {}),
            json.dumps(parameters or []),
            category,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateMCPServerError(
            f"MCP '{package_id}' already installed from '{discovery_service_id}'"
        ) from exc
    assert row is not None
    _log.info(
        "mcp_catalog.install",
        discovery_service_id=discovery_service_id,
        package_id=package_id,
    )
    return _row(row)


async def update_parameters(
    mcp_id: UUID, parameters: dict
) -> MCPServerSummary:
    row = await fetch_one(
        f"""
        UPDATE mcp_servers SET parameters = $2::jsonb, updated_at = NOW()
        WHERE id = $1
        RETURNING {_COLS}
        """,
        mcp_id,
        json.dumps(parameters),
    )
    if row is None:
        raise MCPServerNotFoundError(f"MCP server {mcp_id} not found")
    _log.info("mcp_catalog.update_parameters", mcp_id=str(mcp_id))
    return _row(row)


async def delete(mcp_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM mcp_servers WHERE id = $1", mcp_id
        )
    if result == "DELETE 0":
        raise MCPServerNotFoundError(f"MCP server {mcp_id} not found")
    _log.info("mcp_catalog.delete", mcp_id=str(mcp_id))
