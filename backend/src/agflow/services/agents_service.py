from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one, get_pool
from agflow.schemas.agents import (
    AgentCreate,
    AgentDetail,
    AgentMCPBinding,
    AgentSkillBinding,
    AgentSummary,
    AgentUpdate,
    ImageStatus,
)
from agflow.services import build_service

_log = structlog.get_logger(__name__)

_COLS = (
    "id, slug, display_name, description, dockerfile_id, role_id, env_vars, "
    "timeout_seconds, workspace_path, network_mode, graceful_shutdown_secs, "
    "force_kill_delay_secs, is_assistant, created_at, updated_at"
)


class AgentNotFoundError(Exception):
    pass


class DuplicateAgentError(Exception):
    pass


class InvalidReferenceError(Exception):
    pass


def _summary(row: dict[str, Any]) -> AgentSummary:
    data = dict(row)
    env = data.get("env_vars")
    if isinstance(env, str):
        data["env_vars"] = json.loads(env)
    return AgentSummary(**data)


async def _insert_bindings(
    conn: asyncpg.Connection,
    agent_id: UUID,
    mcp_bindings: list[AgentMCPBinding],
    skill_bindings: list[AgentSkillBinding],
) -> None:
    for b in mcp_bindings:
        await conn.execute(
            """
            INSERT INTO agent_mcp_servers
                (agent_id, mcp_server_id, parameters_override, position)
            VALUES ($1, $2, $3::jsonb, $4)
            """,
            agent_id,
            b.mcp_server_id,
            json.dumps(b.parameters_override),
            b.position,
        )
    for b in skill_bindings:
        await conn.execute(
            """
            INSERT INTO agent_skills (agent_id, skill_id, position)
            VALUES ($1, $2, $3)
            """,
            agent_id,
            b.skill_id,
            b.position,
        )


async def _load_bindings(
    conn: asyncpg.Connection, agent_id: UUID
) -> tuple[list[AgentMCPBinding], list[AgentSkillBinding]]:
    mcp_rows = await conn.fetch(
        """
        SELECT mcp_server_id, parameters_override, position
        FROM agent_mcp_servers
        WHERE agent_id = $1
        ORDER BY position ASC, mcp_server_id ASC
        """,
        agent_id,
    )
    skill_rows = await conn.fetch(
        """
        SELECT skill_id, position
        FROM agent_skills
        WHERE agent_id = $1
        ORDER BY position ASC, skill_id ASC
        """,
        agent_id,
    )
    mcp = [
        AgentMCPBinding(
            mcp_server_id=r["mcp_server_id"],
            parameters_override=json.loads(r["parameters_override"])
            if isinstance(r["parameters_override"], str)
            else r["parameters_override"],
            position=r["position"],
        )
        for r in mcp_rows
    ]
    skills = [
        AgentSkillBinding(skill_id=r["skill_id"], position=r["position"])
        for r in skill_rows
    ]
    return mcp, skills


async def _compute_image_status(dockerfile_id: str) -> ImageStatus:
    latest = await build_service.get_latest_build(dockerfile_id)
    if latest is None or latest["status"] != "success":
        return "missing"
    files = await fetch_all(
        "SELECT path, content FROM dockerfile_files WHERE dockerfile_id = $1",
        dockerfile_id,
    )
    if not files:
        return "missing"
    current_hash = build_service.compute_hash(files)
    if current_hash != latest["content_hash"]:
        return "stale"
    return "fresh"


async def _detail_from_summary(
    conn: asyncpg.Connection, summary: AgentSummary
) -> AgentDetail:
    mcp, skills = await _load_bindings(conn, summary.id)
    image_status = await _compute_image_status(summary.dockerfile_id)
    return AgentDetail(
        **summary.model_dump(),
        mcp_bindings=mcp,
        skill_bindings=skills,
        image_status=image_status,
    )


def _translate_fk_error(exc: asyncpg.ForeignKeyViolationError) -> Exception:
    detail = str(exc)
    if "dockerfile_id" in detail:
        return InvalidReferenceError(f"dockerfile_id not found: {detail}")
    if "role_id" in detail:
        return InvalidReferenceError(f"role_id not found: {detail}")
    if "mcp_server_id" in detail:
        return InvalidReferenceError(f"mcp_server_id not found: {detail}")
    if "skill_id" in detail:
        return InvalidReferenceError(f"skill_id not found: {detail}")
    return InvalidReferenceError(detail)


async def create(payload: AgentCreate) -> AgentDetail:
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        try:
            row = await conn.fetchrow(
                f"""
                    INSERT INTO agents
                        (slug, display_name, description, dockerfile_id, role_id,
                         env_vars, timeout_seconds, workspace_path, network_mode,
                         graceful_shutdown_secs, force_kill_delay_secs)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11)
                    RETURNING {_COLS}
                    """,
                payload.slug,
                payload.display_name,
                payload.description,
                payload.dockerfile_id,
                payload.role_id,
                json.dumps(payload.env_vars),
                payload.timeout_seconds,
                payload.workspace_path,
                payload.network_mode,
                payload.graceful_shutdown_secs,
                payload.force_kill_delay_secs,
            )
        except asyncpg.UniqueViolationError as exc:
            raise DuplicateAgentError(
                f"Agent slug '{payload.slug}' already exists"
            ) from exc
        except asyncpg.ForeignKeyViolationError as exc:
            raise _translate_fk_error(exc) from exc
        assert row is not None
        summary = _summary(dict(row))
        try:
            await _insert_bindings(
                conn, summary.id, payload.mcp_bindings, payload.skill_bindings
            )
        except asyncpg.ForeignKeyViolationError as exc:
            raise _translate_fk_error(exc) from exc
        detail = await _detail_from_summary(conn, summary)
    _log.info("agents.create", agent_id=str(detail.id), slug=detail.slug)
    return detail


async def list_all() -> list[AgentSummary]:
    # Computes `has_errors` in one pass: true when at least one of the
    # agent's profiles references a document UUID that no longer exists
    # in `role_documents` (e.g. document deleted, or agent's role changed).
    rows = await fetch_all(
        f"""
        SELECT {_COLS},
               EXISTS (
                 SELECT 1 FROM agent_profiles p
                 WHERE p.agent_id = agents.id
                   AND EXISTS (
                     SELECT 1
                     FROM unnest(p.document_ids) AS doc_id
                     WHERE NOT EXISTS (
                       SELECT 1 FROM role_documents rd WHERE rd.id = doc_id
                     )
                   )
               ) AS has_errors
        FROM agents
        ORDER BY display_name ASC
        """
    )
    return [_summary(r) for r in rows]


async def get_by_id(agent_id: UUID) -> AgentDetail:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_COLS} FROM agents WHERE id = $1", agent_id
        )
        if row is None:
            raise AgentNotFoundError(f"Agent {agent_id} not found")
        return await _detail_from_summary(conn, _summary(dict(row)))


async def update(agent_id: UUID, payload: AgentUpdate) -> AgentDetail:
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        try:
            row = await conn.fetchrow(
                f"""
                    UPDATE agents SET
                        display_name = $2,
                        description = $3,
                        dockerfile_id = $4,
                        role_id = $5,
                        env_vars = $6::jsonb,
                        timeout_seconds = $7,
                        workspace_path = $8,
                        network_mode = $9,
                        graceful_shutdown_secs = $10,
                        force_kill_delay_secs = $11,
                        updated_at = NOW()
                    WHERE id = $1
                    RETURNING {_COLS}
                    """,
                agent_id,
                payload.display_name,
                payload.description,
                payload.dockerfile_id,
                payload.role_id,
                json.dumps(payload.env_vars),
                payload.timeout_seconds,
                payload.workspace_path,
                payload.network_mode,
                payload.graceful_shutdown_secs,
                payload.force_kill_delay_secs,
            )
        except asyncpg.ForeignKeyViolationError as exc:
            raise _translate_fk_error(exc) from exc
        if row is None:
            raise AgentNotFoundError(f"Agent {agent_id} not found")
        await conn.execute(
            "DELETE FROM agent_mcp_servers WHERE agent_id = $1", agent_id
        )
        await conn.execute(
            "DELETE FROM agent_skills WHERE agent_id = $1", agent_id
        )
        try:
            await _insert_bindings(
                conn, agent_id, payload.mcp_bindings, payload.skill_bindings
            )
        except asyncpg.ForeignKeyViolationError as exc:
            raise _translate_fk_error(exc) from exc
        detail = await _detail_from_summary(conn, _summary(dict(row)))
    _log.info("agents.update", agent_id=str(agent_id))
    return detail


async def delete(agent_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM agents WHERE id = $1", agent_id)
    if result == "DELETE 0":
        raise AgentNotFoundError(f"Agent {agent_id} not found")
    _log.info("agents.delete", agent_id=str(agent_id))


async def duplicate(
    agent_id: UUID, new_slug: str, new_display_name: str
) -> AgentDetail:
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
    )
    return await create(payload)


async def get_assistant() -> AgentSummary | None:
    row = await fetch_one(
        f"SELECT {_COLS} FROM agents WHERE is_assistant = TRUE LIMIT 1"
    )
    return _summary(row) if row else None


async def set_assistant(agent_id: UUID) -> None:
    """Mark an agent as the application assistant. Clears the flag on all others."""
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE agents SET is_assistant = FALSE WHERE is_assistant = TRUE")
        result = await conn.execute(
            "UPDATE agents SET is_assistant = TRUE WHERE id = $1", agent_id
        )
    if result == "UPDATE 0":
        raise AgentNotFoundError(f"Agent {agent_id} not found")
    _log.info("agents.set_assistant", agent_id=str(agent_id))


async def clear_assistant() -> None:
    await execute("UPDATE agents SET is_assistant = FALSE WHERE is_assistant = TRUE")
