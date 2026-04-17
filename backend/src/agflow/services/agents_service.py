"""Agents service — fully filesystem-based.

Each agent lives at {AGFLOW_DATA_DIR}/agents/{slug}/agent.json.
UUIDs are deterministic: UUID5(slug).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from agflow.schemas.agents import (
    AgentCreate,
    AgentDetail,
    AgentMCPBinding,
    AgentSkillBinding,
    AgentSummary,
    AgentUpdate,
    ImageStatus,
)
from agflow.services import agent_files_service, build_service

_log = structlog.get_logger(__name__)


class AgentNotFoundError(Exception):
    pass


class DuplicateAgentError(Exception):
    pass


class InvalidReferenceError(Exception):
    pass


def _slug_to_id(slug: str) -> UUID:
    return agent_files_service.agent_id_from_slug(slug)


def _summary_from_disk(slug: str) -> AgentSummary:
    data = agent_files_service.read_agent(slug)
    if not data:
        raise AgentNotFoundError(f"Agent '{slug}' not found on disk")
    import os
    agent_dir = os.path.join(
        os.environ.get("AGFLOW_DATA_DIR", "/app/data"), "agents", slug
    )
    try:
        mtime = os.path.getmtime(os.path.join(agent_dir, "agent.json"))
        ctime = os.path.getctime(os.path.join(agent_dir, "agent.json"))
    except OSError:
        mtime = ctime = 0
    return AgentSummary(
        id=_slug_to_id(slug),
        slug=slug,
        display_name=data.get("display_name", slug),
        description=data.get("description", ""),
        dockerfile_id=data.get("dockerfile_id", ""),
        role_id=data.get("role_id", ""),
        env_vars={
            "env_overrides": data.get("env_overrides", {}),
            "mount_overrides": data.get("mount_overrides", {}),
            "param_overrides": data.get("param_overrides", {}),
        },
        timeout_seconds=data.get("timeout_seconds", 600),
        workspace_path=data.get("workspace_path", ""),
        network_mode=data.get("network_mode", "bridge"),
        graceful_shutdown_secs=data.get("graceful_shutdown_secs", 30),
        force_kill_delay_secs=data.get("force_kill_delay_secs", 10),
        is_assistant=data.get("is_assistant", False),
        prompt_template_slug=data.get("prompt_template_slug", ""),
        prompt_template_culture=data.get("prompt_template_culture", ""),
        created_at=datetime.fromtimestamp(ctime, tz=UTC),
        updated_at=datetime.fromtimestamp(mtime, tz=UTC),
    )


async def _compute_image_status(dockerfile_id: str) -> ImageStatus:
    from agflow.services import dockerfile_files_service

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


async def _detail_from_summary(summary: AgentSummary) -> AgentDetail:
    data = agent_files_service.read_agent(summary.slug)
    mcp_bindings = [
        AgentMCPBinding(
            mcp_server_id=b.get("catalog_mcp_id", ""),
            parameters_override=b.get("config_overrides", {}),
            position=b.get("position", 0),
        )
        for b in data.get("mcp_bindings", [])
    ]
    skill_bindings = [
        AgentSkillBinding(catalog_skill_id=b.get("catalog_skill_id", ""))
        for b in data.get("skill_bindings", [])
    ]
    image_status = await _compute_image_status(summary.dockerfile_id) if summary.dockerfile_id else "missing"
    return AgentDetail(
        **summary.model_dump(),
        mcp_bindings=mcp_bindings,
        skill_bindings=skill_bindings,
        image_status=image_status,
    )


def _payload_to_disk(slug: str, payload: AgentCreate | AgentUpdate, existing: dict | None = None) -> dict[str, Any]:
    return {
        "slug": slug,
        "display_name": payload.display_name,
        "description": payload.description,
        "dockerfile_id": payload.dockerfile_id,
        "role_id": payload.role_id,
        "env_overrides": payload.env_vars.get("env_overrides", {}) if isinstance(payload.env_vars, dict) else {},
        "mount_overrides": payload.env_vars.get("mount_overrides", {}) if isinstance(payload.env_vars, dict) else {},
        "param_overrides": payload.env_vars.get("param_overrides", {}) if isinstance(payload.env_vars, dict) else {},
        "timeout_seconds": payload.timeout_seconds,
        "workspace_path": payload.workspace_path,
        "network_mode": payload.network_mode,
        "graceful_shutdown_secs": payload.graceful_shutdown_secs,
        "force_kill_delay_secs": payload.force_kill_delay_secs,
        "is_assistant": existing.get("is_assistant", False) if existing else False,
        "prompt_template_slug": payload.prompt_template_slug if hasattr(payload, "prompt_template_slug") and payload.prompt_template_slug is not None else (existing.get("prompt_template_slug", "") if existing else ""),
        "prompt_template_culture": payload.prompt_template_culture if hasattr(payload, "prompt_template_culture") and payload.prompt_template_culture is not None else (existing.get("prompt_template_culture", "") if existing else ""),
        "mcp_bindings": [
            {
                "catalog_mcp_id": b.mcp_server_id if hasattr(b, "mcp_server_id") else b.get("mcp_server_id", ""),
                "config_overrides": b.parameters_override if hasattr(b, "parameters_override") else b.get("parameters_override", {}),
                "position": b.position if hasattr(b, "position") else b.get("position", 0),
            }
            for b in (payload.mcp_bindings or [])
        ],
        "skill_bindings": [
            {
                "catalog_skill_id": b.catalog_skill_id if hasattr(b, "catalog_skill_id") else b.get("catalog_skill_id", ""),
            }
            for b in (payload.skill_bindings or [])
        ],
        "profiles": existing.get("profiles", []) if existing else [],
    }


async def create(payload: AgentCreate) -> AgentDetail:
    existing_slugs = agent_files_service.list_agent_slugs()
    if payload.slug in existing_slugs:
        raise DuplicateAgentError(f"Agent slug '{payload.slug}' already exists")
    data = _payload_to_disk(payload.slug, payload)
    agent_files_service.write_agent(payload.slug, data)
    summary = _summary_from_disk(payload.slug)
    _log.info("agents.create", slug=payload.slug)
    return await _detail_from_summary(summary)


async def list_all() -> list[AgentSummary]:
    slugs = agent_files_service.list_agent_slugs()
    return [_summary_from_disk(s) for s in slugs]


async def get_by_id(agent_id: UUID) -> AgentDetail:
    for slug in agent_files_service.list_agent_slugs():
        if _slug_to_id(slug) == agent_id:
            summary = _summary_from_disk(slug)
            return await _detail_from_summary(summary)
    raise AgentNotFoundError(f"Agent {agent_id} not found")


async def update(agent_id: UUID, payload: AgentUpdate) -> AgentDetail:
    slug = _find_slug(agent_id)
    existing = agent_files_service.read_agent(slug)
    data = _payload_to_disk(slug, payload, existing)
    agent_files_service.write_agent(slug, data)
    summary = _summary_from_disk(slug)
    _log.info("agents.update", slug=slug)
    return await _detail_from_summary(summary)


async def delete(agent_id: UUID) -> None:
    slug = _find_slug(agent_id)
    agent_files_service.delete_agent_dir(slug)
    _log.info("agents.delete", slug=slug)


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
    for slug in agent_files_service.list_agent_slugs():
        data = agent_files_service.read_agent(slug)
        if data.get("is_assistant"):
            return _summary_from_disk(slug)
    return None


async def set_assistant(agent_id: UUID) -> None:
    target_slug = _find_slug(agent_id)
    for slug in agent_files_service.list_agent_slugs():
        data = agent_files_service.read_agent(slug)
        if data.get("is_assistant") and slug != target_slug:
            data["is_assistant"] = False
            agent_files_service.write_agent(slug, data)
    data = agent_files_service.read_agent(target_slug)
    data["is_assistant"] = True
    agent_files_service.write_agent(target_slug, data)
    _log.info("agents.set_assistant", slug=target_slug)


async def clear_assistant() -> None:
    for slug in agent_files_service.list_agent_slugs():
        data = agent_files_service.read_agent(slug)
        if data.get("is_assistant"):
            data["is_assistant"] = False
            agent_files_service.write_agent(slug, data)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _find_slug(agent_id: UUID) -> str:
    for slug in agent_files_service.list_agent_slugs():
        if _slug_to_id(slug) == agent_id:
            return slug
    raise AgentNotFoundError(f"Agent {agent_id} not found")
