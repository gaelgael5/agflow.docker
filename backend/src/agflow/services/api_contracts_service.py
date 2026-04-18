from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one
from agflow.schemas.contracts import ContractDetail, ContractSummary, TagSummary
from agflow.services import openapi_parser

_log = structlog.get_logger(__name__)

_SUMMARY_COLS = (
    "id, agent_id, slug, display_name, description, source_type, source_url, "
    "base_url, runtime_base_url, auth_header, auth_prefix, auth_secret_ref, parsed_tags, "
    "output_dir, tag_overrides, managed_by_instance, position, created_at, updated_at"
)

_DETAIL_COLS = f"{_SUMMARY_COLS}, spec_content"


def _parse_tags(raw: Any, overrides: dict[str, str] | None = None) -> list[TagSummary]:
    tags = raw if isinstance(raw, list) else json.loads(raw or "[]")
    ovr = overrides or {}
    return [
        TagSummary(
            slug=t.get("slug", ""),
            name=t.get("name", ""),
            description=t.get("description", ""),
            resolved_description=openapi_parser.resolve_tag_description(t, ovr),
            operation_count=t.get("operation_count", 0),
        )
        for t in tags
    ]


def _row_to_summary(row: dict[str, Any]) -> ContractSummary:
    ovr = json.loads(row["tag_overrides"]) if isinstance(row["tag_overrides"], str) else (row.get("tag_overrides") or {})
    return ContractSummary(
        id=row["id"],
        agent_id=row["agent_id"],
        slug=row["slug"],
        display_name=row["display_name"],
        description=row["description"],
        source_type=row["source_type"],
        source_url=row["source_url"],
        base_url=row["base_url"],
        runtime_base_url=row.get("runtime_base_url", ""),
        auth_header=row["auth_header"],
        auth_prefix=row["auth_prefix"],
        auth_secret_ref=row["auth_secret_ref"],
        parsed_tags=_parse_tags(row["parsed_tags"], ovr),
        output_dir=row.get("output_dir", "workspace/docs/ctr"),
        tag_overrides=ovr,
        managed_by_instance=row.get("managed_by_instance"),
        position=row["position"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_detail(row: dict[str, Any]) -> ContractDetail:
    summary = _row_to_summary(row)
    return ContractDetail(
        **summary.model_dump(),
        spec_content=row["spec_content"],
    )


class ContractNotFoundError(Exception):
    pass


class DuplicateContractError(Exception):
    pass


async def list_for_agent(agent_id: str) -> list[ContractSummary]:
    rows = await fetch_all(
        f"SELECT {_SUMMARY_COLS} FROM agent_api_contracts "
        "WHERE agent_id = $1 ORDER BY position, slug",
        agent_id,
    )
    return [_row_to_summary(r) for r in rows]


async def get_by_id(contract_id: UUID) -> ContractDetail:
    row = await fetch_one(
        f"SELECT {_DETAIL_COLS} FROM agent_api_contracts WHERE id = $1",
        contract_id,
    )
    if row is None:
        raise ContractNotFoundError(f"Contract {contract_id} not found")
    return _row_to_detail(row)


async def create(
    agent_id: str,
    slug: str,
    display_name: str,
    description: str,
    source_type: str,
    source_url: str | None,
    spec_content: str,
    base_url: str,
    runtime_base_url: str = "",
    auth_header: str = "Authorization",
    auth_prefix: str = "Bearer",
    auth_secret_ref: str | None = None,
    output_dir: str = "workspace/docs/ctr",
    tag_overrides: dict | None = None,
) -> ContractSummary:
    tags = openapi_parser.parse_openapi_tags(spec_content)
    tag_summaries = [
        {
            "slug": t["slug"],
            "name": t["name"],
            "description": t["description"],
            "operation_count": t["operation_count"],
        }
        for t in tags
    ]
    if not base_url:
        base_url = openapi_parser.detect_base_url(spec_content)

    try:
        row = await fetch_one(
            f"""
            INSERT INTO agent_api_contracts (
                agent_id, slug, display_name, description, source_type,
                source_url, spec_content, base_url, runtime_base_url, auth_header, auth_prefix,
                auth_secret_ref, parsed_tags, output_dir, tag_overrides
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14, $15::jsonb)
            RETURNING {_SUMMARY_COLS}
            """,
            agent_id,
            slug,
            display_name,
            description,
            source_type,
            source_url,
            spec_content,
            base_url,
            runtime_base_url,
            auth_header,
            auth_prefix,
            auth_secret_ref,
            json.dumps(tag_summaries),
            output_dir,
            json.dumps(tag_overrides or {}),
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateContractError(
            f"Contract '{slug}' already exists for this agent"
        ) from exc
    assert row is not None
    _log.info("api_contracts.create", agent_id=agent_id, slug=slug, tags=len(tags))
    return _row_to_summary(row)


async def update(contract_id: UUID, **kwargs: Any) -> ContractSummary:
    # Raises ContractNotFoundError if the contract does not exist.
    await get_by_id(contract_id)

    updates: dict[str, Any] = {}
    for field in (
        "display_name",
        "description",
        "source_url",
        "spec_content",
        "base_url",
        "runtime_base_url",
        "auth_header",
        "auth_prefix",
        "auth_secret_ref",
        "output_dir",
        "tag_overrides",
    ):
        if field in kwargs and kwargs[field] is not None:
            updates[field] = kwargs[field]

    if not updates:
        row = await fetch_one(
            f"SELECT {_SUMMARY_COLS} FROM agent_api_contracts WHERE id = $1",
            contract_id,
        )
        assert row is not None
        return _row_to_summary(row)

    if "spec_content" in updates:
        tags = openapi_parser.parse_openapi_tags(updates["spec_content"])
        updates["parsed_tags"] = json.dumps(
            [
                {
                    "slug": t["slug"],
                    "name": t["name"],
                    "description": t["description"],
                    "operation_count": t["operation_count"],
                }
                for t in tags
            ]
        )

    set_parts = []
    values: list[Any] = []
    for i, (k, v) in enumerate(updates.items(), start=1):
        if k == "parsed_tags" or k == "tag_overrides":
            set_parts.append(f"{k} = ${i}::jsonb")
            values.append(json.dumps(v) if isinstance(v, dict) else v)
        else:
            set_parts.append(f"{k} = ${i}")
            values.append(v)
    values.append(contract_id)
    set_clause = ", ".join(set_parts)

    row = await fetch_one(
        f"UPDATE agent_api_contracts SET {set_clause}, updated_at = NOW() "
        f"WHERE id = ${len(values)} RETURNING {_SUMMARY_COLS}",
        *values,
    )
    assert row is not None
    _log.info("api_contracts.update", contract_id=str(contract_id))
    return _row_to_summary(row)


async def delete(contract_id: UUID) -> None:
    row = await fetch_one(
        "DELETE FROM agent_api_contracts WHERE id = $1 RETURNING id",
        contract_id,
    )
    if row is None:
        raise ContractNotFoundError(f"Contract {contract_id} not found")
    _log.info("api_contracts.delete", contract_id=str(contract_id))


async def refresh_from_url(contract_id: UUID) -> ContractSummary:
    """Re-fetch spec from source_url, re-parse tags, preserve tag_overrides."""
    import httpx

    detail = await get_by_id(contract_id)
    if not detail.source_url:
        raise ContractNotFoundError(f"Contract {contract_id} has no source_url")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=True,
    ) as client:
        response = await client.get(detail.source_url)
        response.raise_for_status()

    new_spec = response.text
    tags = openapi_parser.parse_openapi_tags(new_spec)
    tag_summaries = json.dumps([
        {"slug": t["slug"], "name": t["name"], "description": t["description"], "operation_count": t["operation_count"]}
        for t in tags
    ])

    row = await fetch_one(
        f"UPDATE agent_api_contracts SET spec_content = $1, parsed_tags = $2::jsonb, updated_at = NOW() "
        f"WHERE id = $3 RETURNING {_SUMMARY_COLS}",
        new_spec, tag_summaries, contract_id,
    )
    assert row is not None
    _log.info("api_contracts.refresh", contract_id=str(contract_id), tags=len(tags))
    return _row_to_summary(row)


async def reorder(agent_id: str, ordered_ids: list[UUID]) -> list[ContractSummary]:
    """Reorder contracts for an agent by updating positions."""
    from agflow.db.pool import execute

    for position, cid in enumerate(ordered_ids):
        await execute(
            "UPDATE agent_api_contracts SET position = $1, updated_at = NOW() "
            "WHERE id = $2 AND agent_id = $3",
            position, cid, agent_id,
        )
    _log.info("api_contracts.reorder", agent_id=agent_id, count=len(ordered_ids))
    return await list_for_agent(agent_id)
