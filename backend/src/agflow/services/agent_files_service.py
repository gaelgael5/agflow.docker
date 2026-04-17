"""Agent filesystem storage.

Each agent lives at {AGFLOW_DATA_DIR}/agents/{slug}/agent.json
Generated output goes to {AGFLOW_DATA_DIR}/agents/{slug}/generated/
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

import structlog

_log = structlog.get_logger(__name__)

_AGENT_NS = uuid.UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901")


def _data_dir() -> str:
    return os.environ.get("AGFLOW_DATA_DIR", "/app/data")


def _agent_dir(slug: str) -> str:
    return os.path.join(_data_dir(), "agents", slug)


def agent_id_from_slug(slug: str) -> uuid.UUID:
    return uuid.uuid5(_AGENT_NS, slug)


# ── Read / Write ─────────────────────────────────────────────────────────────


def read_agent(slug: str) -> dict[str, Any]:
    path = os.path.join(_agent_dir(slug), "agent.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def write_agent(slug: str, data: dict[str, Any]) -> None:
    if not data or not data.get("slug"):
        _log.warning("agent_files.write.skip_empty", slug=slug)
        return
    d = _agent_dir(slug)
    os.makedirs(d, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if len(content) < 10:
        _log.warning("agent_files.write.skip_too_small", slug=slug, size=len(content))
        return
    with open(os.path.join(d, "agent.json"), "w", encoding="utf-8") as f:
        f.write(content)


def delete_agent_dir(slug: str) -> None:
    import shutil
    d = _agent_dir(slug)
    if os.path.isdir(d):
        shutil.rmtree(d)


def list_agent_slugs() -> list[str]:
    agents_dir = os.path.join(_data_dir(), "agents")
    if not os.path.isdir(agents_dir):
        return []
    return sorted(
        name for name in os.listdir(agents_dir)
        if os.path.isfile(os.path.join(agents_dir, name, "agent.json"))
    )


# ── Migration ────────────────────────────────────────────────────────────────


async def migrate_db_to_disk() -> None:
    """One-time migration: read agents from DB and write agent.json to disk."""
    from agflow.db.pool import fetch_all

    try:
        agents = await fetch_all(
            "SELECT id, slug, display_name, description, dockerfile_id, role_id, "
            "env_vars, timeout_seconds, workspace_path, network_mode, "
            "graceful_shutdown_secs, force_kill_delay_secs, is_assistant "
            "FROM agents"
        )
    except Exception as exc:
        _log.warning("agent_files.migrate.skip", reason=str(exc))
        return

    migrated = 0
    for agent in agents:
        slug = agent["slug"]
        agent_json_path = os.path.join(_agent_dir(slug), "agent.json")
        if os.path.isfile(agent_json_path):
            continue

        agent_id = agent["id"]

        # Load MCP bindings
        try:
            mcp_rows = await fetch_all(
                "SELECT catalog_mcp_id, config_overrides, position "
                "FROM agent_mcp_servers WHERE agent_id = $1 ORDER BY position",
                agent_id,
            )
            mcp_bindings = [
                {
                    "catalog_mcp_id": str(r["catalog_mcp_id"]),
                    "config_overrides": r["config_overrides"] or {},
                    "position": r["position"],
                }
                for r in mcp_rows
            ]
        except Exception:
            mcp_bindings = []

        # Load skill bindings
        try:
            skill_rows = await fetch_all(
                "SELECT catalog_skill_id FROM agent_skills WHERE agent_id = $1",
                agent_id,
            )
            skill_bindings = [
                {"catalog_skill_id": str(r["catalog_skill_id"])}
                for r in skill_rows
            ]
        except Exception:
            skill_bindings = []

        # Load profiles and convert document_ids to paths
        try:
            profile_rows = await fetch_all(
                "SELECT name, description, document_ids "
                "FROM agent_profiles WHERE agent_id = $1",
                agent_id,
            )
            profiles = []
            for pr in profile_rows:
                doc_paths = await _resolve_doc_ids_to_paths(
                    agent["role_id"], pr["document_ids"] or []
                )
                profiles.append({
                    "name": pr["name"],
                    "description": pr["description"] or "",
                    "documents": doc_paths,
                })
        except Exception:
            profiles = []

        env_vars = agent["env_vars"]
        if isinstance(env_vars, str):
            env_vars = json.loads(env_vars) if env_vars else {}

        data = {
            "slug": slug,
            "display_name": agent["display_name"],
            "description": agent["description"],
            "dockerfile_id": agent["dockerfile_id"],
            "role_id": agent["role_id"],
            "env_vars": env_vars or {},
            "timeout_seconds": agent["timeout_seconds"],
            "workspace_path": agent["workspace_path"],
            "network_mode": agent["network_mode"],
            "graceful_shutdown_secs": agent["graceful_shutdown_secs"],
            "force_kill_delay_secs": agent["force_kill_delay_secs"],
            "is_assistant": agent["is_assistant"],
            "mcp_bindings": mcp_bindings,
            "skill_bindings": skill_bindings,
            "profiles": profiles,
        }
        write_agent(slug, data)
        migrated += 1

    _log.info("agent_files.migrate.done", migrated=migrated)


async def _resolve_doc_ids_to_paths(role_id: str, doc_ids: list) -> list[str]:
    """Convert document UUIDs to filesystem paths like 'roles/Assistant plateforme.md'."""
    from agflow.services import role_documents_service

    paths = []
    docs = await role_documents_service.list_for_role(role_id)
    doc_map = {str(d.id): d for d in docs}
    for did in doc_ids:
        doc = doc_map.get(str(did))
        if doc:
            paths.append(f"{doc.section}/{doc.name}.md")
    return paths
