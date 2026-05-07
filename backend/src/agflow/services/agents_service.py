from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one, get_pool
from agflow.schemas.agents import (
    AgentCreate,
    AgentDetail,
    AgentGeneration,
    AgentMCPBinding,
    AgentSkillBinding,
    AgentSummary,
    AgentUpdate,
    ImageStatus,
)

_log = structlog.get_logger(__name__)

_AGENT_NS = uuid.UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901")


class AgentNotFoundError(Exception):
    pass


class DuplicateAgentError(Exception):
    pass


class InvalidReferenceError(Exception):
    pass


def _slug_to_uuid(slug: str) -> UUID:
    return uuid.uuid5(_AGENT_NS, slug)


_COLS = (
    "slug, id, display_name, description, dockerfile_id, role_id, "
    "env_overrides, mount_overrides, param_overrides, "
    "timeout_seconds, workspace_path, network_mode, "
    "graceful_shutdown_secs, force_kill_delay_secs, is_assistant, "
    "mcp_template_slug, mcp_template_culture, mcp_config_filename, "
    "skills_template_slug, skills_template_culture, skills_config_filename, "
    "prompt_template_slug, prompt_template_culture, prompt_filename, "
    "mcp_bindings, skill_bindings, generations, "
    "created_at, updated_at"
)


def _row_to_summary(row: dict[str, Any]) -> AgentSummary:
    return AgentSummary(
        id=row["id"],
        slug=row["slug"],
        display_name=row["display_name"],
        description=row["description"],
        dockerfile_id=row["dockerfile_id"],
        role_id=row["role_id"],
        env_vars={
            "env_overrides": dict(row["env_overrides"] or {}),
            "mount_overrides": dict(row["mount_overrides"] or {}),
            "param_overrides": dict(row["param_overrides"] or {}),
        },
        timeout_seconds=row["timeout_seconds"],
        workspace_path=row["workspace_path"],
        network_mode=row["network_mode"],
        graceful_shutdown_secs=row["graceful_shutdown_secs"],
        force_kill_delay_secs=row["force_kill_delay_secs"],
        is_assistant=row["is_assistant"],
        mcp_template_slug=row["mcp_template_slug"],
        mcp_template_culture=row["mcp_template_culture"],
        mcp_config_filename=row["mcp_config_filename"],
        skills_template_slug=row["skills_template_slug"],
        skills_template_culture=row["skills_template_culture"],
        skills_config_filename=row["skills_config_filename"],
        prompt_template_slug=row["prompt_template_slug"],
        prompt_template_culture=row["prompt_template_culture"],
        prompt_filename=row["prompt_filename"],
        generations=[AgentGeneration(**g) for g in (row["generations"] or [])],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _compute_image_status(dockerfile_id: str) -> ImageStatus:
    from agflow.services import build_service, dockerfile_files_service

    latest = await build_service.get_latest_build(dockerfile_id)
    if latest is None or latest["status"] != "success":
        return "missing"
    disk_files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    if not disk_files:
        return "missing"
    files_for_hash = [{"path": f.path, "content": f.content} for f in disk_files]
    current_hash = build_service.compute_hash(files_for_hash)
    if current_hash != latest["content_hash"]:
        return "stale"
    return "fresh"


async def _detail_from_row(row: dict[str, Any]) -> AgentDetail:
    summary = _row_to_summary(row)
    mcp_bindings = [
        AgentMCPBinding(
            mcp_server_id=UUID(b["catalog_mcp_id"]),
            parameters_override=b.get("config_overrides", {}),
            position=b.get("position", 0),
        )
        for b in (row["mcp_bindings"] or [])
        if b.get("catalog_mcp_id")
    ]
    skill_bindings = [
        AgentSkillBinding(skill_id=UUID(b["catalog_skill_id"]), position=b.get("position", 0))
        for b in (row["skill_bindings"] or [])
        if b.get("catalog_skill_id")
    ]
    image_status = (
        await _compute_image_status(summary.dockerfile_id)
        if summary.dockerfile_id
        else "missing"
    )
    return AgentDetail(
        **summary.model_dump(),
        mcp_bindings=mcp_bindings,
        skill_bindings=skill_bindings,
        image_status=image_status,
    )


def _env(payload: AgentCreate | AgentUpdate, key: str) -> str:
    env = payload.env_vars if isinstance(payload.env_vars, dict) else {}
    return json.dumps(env.get(key, {}))


def _bindings_json(payload: AgentCreate | AgentUpdate) -> tuple[str, str]:
    mcp = json.dumps([
        {
            "catalog_mcp_id": str(b.mcp_server_id),
            "config_overrides": b.parameters_override,
            "position": b.position,
        }
        for b in (payload.mcp_bindings or [])
    ])
    skill = json.dumps([
        {"catalog_skill_id": str(b.skill_id), "position": b.position}
        for b in (payload.skill_bindings or [])
    ])
    return mcp, skill


async def create(payload: AgentCreate) -> AgentDetail:
    agent_id = _slug_to_uuid(payload.slug)
    mcp_json, skill_json = _bindings_json(payload)
    gen_json = json.dumps([g.model_dump(mode="json") for g in (payload.generations or [])])
    try:
        row = await fetch_one(
            f"""
            INSERT INTO agents (
                slug, id, display_name, description, dockerfile_id, role_id,
                env_overrides, mount_overrides, param_overrides,
                timeout_seconds, workspace_path, network_mode,
                graceful_shutdown_secs, force_kill_delay_secs,
                mcp_template_slug, mcp_template_culture, mcp_config_filename,
                skills_template_slug, skills_template_culture, skills_config_filename,
                prompt_template_slug, prompt_template_culture, prompt_filename,
                mcp_bindings, skill_bindings, generations
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26
            ) RETURNING {_COLS}
            """,
            payload.slug, agent_id, payload.display_name, payload.description,
            payload.dockerfile_id, payload.role_id,
            _env(payload, "env_overrides"),
            _env(payload, "mount_overrides"),
            _env(payload, "param_overrides"),
            payload.timeout_seconds, payload.workspace_path, payload.network_mode,
            payload.graceful_shutdown_secs, payload.force_kill_delay_secs,
            payload.mcp_template_slug, payload.mcp_template_culture, payload.mcp_config_filename,
            payload.skills_template_slug, payload.skills_template_culture, payload.skills_config_filename,
            payload.prompt_template_slug, payload.prompt_template_culture, payload.prompt_filename,
            mcp_json, skill_json, gen_json,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateAgentError(f"Agent slug '{payload.slug}' already exists") from exc
    assert row is not None
    _log.info("agents.create", slug=payload.slug)
    return await _detail_from_row(row)


async def list_all() -> list[AgentSummary]:
    rows = await fetch_all(f"SELECT {_COLS} FROM agents ORDER BY display_name ASC")
    return [_row_to_summary(r) for r in rows]


async def get_by_id(agent_id: UUID) -> AgentDetail:
    row = await fetch_one(f"SELECT {_COLS} FROM agents WHERE id = $1", agent_id)
    if row is None:
        raise AgentNotFoundError(f"Agent {agent_id} not found")
    return await _detail_from_row(row)


async def update(agent_id: UUID, payload: AgentUpdate) -> AgentDetail:
    mcp_json, skill_json = _bindings_json(payload)
    gen_json = json.dumps([g.model_dump(mode="json") for g in (payload.generations or [])])
    row = await fetch_one(
        f"""
        UPDATE agents SET
            display_name = $2, description = $3, dockerfile_id = $4, role_id = $5,
            env_overrides = $6, mount_overrides = $7, param_overrides = $8,
            timeout_seconds = $9, workspace_path = $10, network_mode = $11,
            graceful_shutdown_secs = $12, force_kill_delay_secs = $13,
            mcp_template_slug = $14, mcp_template_culture = $15, mcp_config_filename = $16,
            skills_template_slug = $17, skills_template_culture = $18, skills_config_filename = $19,
            prompt_template_slug = $20, prompt_template_culture = $21, prompt_filename = $22,
            mcp_bindings = $23, skill_bindings = $24, generations = $25
        WHERE id = $1
        RETURNING {_COLS}
        """,
        agent_id, payload.display_name, payload.description,
        payload.dockerfile_id, payload.role_id,
        _env(payload, "env_overrides"),
        _env(payload, "mount_overrides"),
        _env(payload, "param_overrides"),
        payload.timeout_seconds, payload.workspace_path, payload.network_mode,
        payload.graceful_shutdown_secs, payload.force_kill_delay_secs,
        payload.mcp_template_slug, payload.mcp_template_culture, payload.mcp_config_filename,
        payload.skills_template_slug, payload.skills_template_culture, payload.skills_config_filename,
        payload.prompt_template_slug, payload.prompt_template_culture, payload.prompt_filename,
        mcp_json, skill_json, gen_json,
    )
    if row is None:
        raise AgentNotFoundError(f"Agent {agent_id} not found")
    _log.info("agents.update", agent_id=str(agent_id))
    return await _detail_from_row(row)


async def delete(agent_id: UUID) -> None:
    result = await execute("DELETE FROM agents WHERE id = $1", agent_id)
    if result == "DELETE 0":
        raise AgentNotFoundError(f"Agent {agent_id} not found")
    _log.info("agents.delete", agent_id=str(agent_id))


async def duplicate(agent_id: UUID, new_slug: str, new_display_name: str) -> AgentDetail:
    source = await get_by_id(agent_id)
    payload = AgentCreate(
        slug=new_slug,
        display_name=new_display_name,
        description=source.description,
        dockerfile_id=source.dockerfile_id,
        role_id=source.role_id,
        env_vars=source.env_vars,
        timeout_seconds=source.timeout_seconds,
        workspace_path=source.workspace_path,
        network_mode=source.network_mode,
        graceful_shutdown_secs=source.graceful_shutdown_secs,
        force_kill_delay_secs=source.force_kill_delay_secs,
        mcp_bindings=source.mcp_bindings,
        skill_bindings=source.skill_bindings,
        generations=source.generations,
    )
    return await create(payload)


async def get_assistant() -> AgentSummary | None:
    row = await fetch_one(f"SELECT {_COLS} FROM agents WHERE is_assistant = TRUE LIMIT 1")
    return _row_to_summary(row) if row else None


async def set_assistant(agent_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        exists = await conn.fetchval("SELECT 1 FROM agents WHERE id = $1", agent_id)
        if not exists:
            raise AgentNotFoundError(f"Agent {agent_id} not found")
        await conn.execute(
            "UPDATE agents SET is_assistant = FALSE WHERE is_assistant = TRUE AND id != $1",
            agent_id,
        )
        await conn.execute("UPDATE agents SET is_assistant = TRUE WHERE id = $1", agent_id)
    _log.info("agents.set_assistant", agent_id=str(agent_id))


async def clear_assistant() -> None:
    await execute("UPDATE agents SET is_assistant = FALSE WHERE is_assistant = TRUE")
