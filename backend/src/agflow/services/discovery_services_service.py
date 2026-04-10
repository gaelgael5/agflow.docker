from __future__ import annotations

from typing import Any

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.catalogs import DiscoveryServiceSummary, ProbeResult
from agflow.services import discovery_client, secrets_service

_log = structlog.get_logger(__name__)

_COLS = (
    "id, name, base_url, api_key_var, description, enabled, "
    "created_at, updated_at"
)


class DiscoveryServiceNotFoundError(Exception):
    pass


class DuplicateDiscoveryServiceError(Exception):
    pass


def _row(row: dict[str, Any]) -> DiscoveryServiceSummary:
    return DiscoveryServiceSummary(**row)


async def create(
    service_id: str,
    name: str,
    base_url: str,
    api_key_var: str | None = None,
    description: str = "",
    enabled: bool = True,
) -> DiscoveryServiceSummary:
    try:
        row = await fetch_one(
            f"""
            INSERT INTO discovery_services
                (id, name, base_url, api_key_var, description, enabled)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING {_COLS}
            """,
            service_id,
            name,
            base_url,
            api_key_var,
            description,
            enabled,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateDiscoveryServiceError(
            f"Discovery service '{service_id}' already exists"
        ) from exc
    assert row is not None
    _log.info("discovery.create", service_id=service_id)
    return _row(row)


async def list_all() -> list[DiscoveryServiceSummary]:
    rows = await fetch_all(
        f"SELECT {_COLS} FROM discovery_services ORDER BY name ASC"
    )
    return [_row(r) for r in rows]


async def get_by_id(service_id: str) -> DiscoveryServiceSummary:
    row = await fetch_one(
        f"SELECT {_COLS} FROM discovery_services WHERE id = $1", service_id
    )
    if row is None:
        raise DiscoveryServiceNotFoundError(
            f"Discovery service '{service_id}' not found"
        )
    return _row(row)


async def update(
    service_id: str,
    **fields: Any,
) -> DiscoveryServiceSummary:
    allowed = {"name", "base_url", "api_key_var", "description", "enabled"}
    sets: list[str] = []
    args: list[Any] = []
    idx = 1
    for key, value in fields.items():
        if value is None or key not in allowed:
            continue
        sets.append(f"{key} = ${idx}")
        args.append(value)
        idx += 1
    if not sets:
        return await get_by_id(service_id)
    sets.append("updated_at = NOW()")
    args.append(service_id)
    row = await fetch_one(
        f"""
        UPDATE discovery_services SET {", ".join(sets)}
        WHERE id = ${idx}
        RETURNING {_COLS}
        """,
        *args,
    )
    if row is None:
        raise DiscoveryServiceNotFoundError(
            f"Discovery service '{service_id}' not found"
        )
    _log.info("discovery.update", service_id=service_id)
    return _row(row)


async def delete(service_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM discovery_services WHERE id = $1", service_id
        )
    if result == "DELETE 0":
        raise DiscoveryServiceNotFoundError(
            f"Discovery service '{service_id}' not found"
        )
    _log.info("discovery.delete", service_id=service_id)


async def _resolve_api_key(api_key_var: str | None) -> str | None:
    if not api_key_var:
        return None
    try:
        env = await secrets_service.resolve_env([api_key_var])
    except secrets_service.SecretNotFoundError:
        return None
    return env.get(api_key_var)


async def test_connectivity(service_id: str) -> ProbeResult:
    service = await get_by_id(service_id)
    api_key = await _resolve_api_key(service.api_key_var)
    if service.api_key_var and api_key is None:
        return ProbeResult(
            ok=False,
            detail=(
                f"api_key_var '{service.api_key_var}' is not set in Module 0 "
                f"(Secrets)"
            ),
        )
    return await discovery_client.probe(service.base_url, api_key)
