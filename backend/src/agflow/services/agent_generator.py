from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID

import structlog

from agflow.services import (
    agent_profiles_service,
    agents_service,
    dockerfile_files_service,
    role_documents_service,
    role_sections_service,
    roles_service,
)
from agflow.services.container_runner import _load_platform_secrets, build_run_config

_log = structlog.get_logger(__name__)


def _agents_dir() -> str:
    base = os.environ.get("AGFLOW_DATA_DIR", "/app/data")
    return os.path.join(base, "agents")


async def generate(
    agent_id: UUID,
    profile_id: UUID | None = None,
    user_secrets: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Generate the full agent workspace on disk.

    Creates {AGFLOW_DATA_DIR}/agents/{slug}/ with:
      - run.sh          — docker run command
      - prompt.md       — identity + profile documents
      - mcp.json        — MCP server configs
      - .env            — resolved environment variables
      - skills/         — skill files
    """
    agent = await agents_service.get_by_id(agent_id)
    slug = agent.slug

    out_dir = os.path.join(_agents_dir(), slug)
    os.makedirs(out_dir, exist_ok=True)

    role = await roles_service.get_by_id(agent.role_id)
    await role_sections_service.list_for_role(agent.role_id)
    documents = await role_documents_service.list_for_role(agent.role_id)

    # Build prompt.md
    prompt_parts = [f"# {role.display_name}\n\n{role.identity_md}"]

    if profile_id:
        profiles = await agent_profiles_service.list_for_agent(agent_id)
        profile = next((p for p in profiles if p.id == profile_id), None)
        if profile:
            doc_ids = set(str(d) for d in profile.document_ids)
            for doc in documents:
                if str(doc.id) in doc_ids:
                    prompt_parts.append(f"\n---\n\n{doc.content_md}")
    else:
        for doc in documents:
            prompt_parts.append(f"\n---\n\n{doc.content_md}")

    prompt_md = "\n".join(prompt_parts)
    _write(out_dir, "prompt.md", prompt_md)

    # Build .env
    platform_secrets = await _load_platform_secrets()
    all_secrets = {**platform_secrets, **(user_secrets or {})}

    env_lines = []
    for k, v in agent.env_vars.items():
        if v.startswith("$") and len(v) > 1:
            resolved = all_secrets.get(v[1:], "")
            env_lines.append(f"{k}={resolved}")
        else:
            env_lines.append(f"{k}={v}")
    _write(out_dir, ".env", "\n".join(env_lines) + "\n")

    # Build mcp.json
    mcp_config = []
    for binding in agent.mcp_bindings:
        mcp_config.append({
            "mcp_server_id": binding.mcp_server_id,
            "config_overrides": binding.config_overrides,
        })
    _write(out_dir, "mcp.json", json.dumps(mcp_config, indent=2, ensure_ascii=False))

    # Skills
    skills_dir = os.path.join(out_dir, "skills")
    os.makedirs(skills_dir, exist_ok=True)
    for binding in agent.skill_bindings:
        _write(skills_dir, f"{binding.catalog_skill_id}.md", "")

    # Build run.sh from Dockerfile.json
    files = await dockerfile_files_service.list_for_dockerfile(agent.dockerfile_id)
    params_file = next((f for f in files if f.path == "Dockerfile.json"), None)

    run_sh_lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    if params_file:
        import secrets as _secrets
        instance_id = _secrets.token_hex(3)
        try:
            from agflow.services import build_service
            tag = build_service.image_tag_for(agent.dockerfile_id, "latest")
        except Exception:
            tag = f"agflow-{agent.dockerfile_id}:latest"

        try:
            name, config = build_run_config(
                dockerfile_id=agent.dockerfile_id,
                params_json_content=params_file.content,
                content_hash="latest",
                instance_id=instance_id,
                extra_env=all_secrets,
            )
            # Build docker run command from config
            cmd_parts = ["docker run"]
            cmd_parts.append(f"--name {name}")
            if config.get("HostConfig", {}).get("NetworkMode"):
                cmd_parts.append(f"--network {config['HostConfig']['NetworkMode']}")
            for env in config.get("Env", []):
                cmd_parts.append(f'-e "{env}"')
            for bind in config.get("HostConfig", {}).get("Binds", []):
                cmd_parts.append(f'-v "{bind}"')
            if config.get("HostConfig", {}).get("Memory"):
                mem_mb = config["HostConfig"]["Memory"] // (1024 * 1024)
                cmd_parts.append(f"--memory {mem_mb}m")
            cmd_parts.append(config.get("Image", tag))
            run_sh_lines.append(" \\\n  ".join(cmd_parts))
        except Exception as exc:
            run_sh_lines.append(f"# Error generating docker command: {exc}")
            run_sh_lines.append(f"# docker run agflow-{agent.dockerfile_id}:latest")
    else:
        run_sh_lines.append("# No Dockerfile.json found")
        run_sh_lines.append(f"docker run agflow-{agent.dockerfile_id}:latest")

    _write(out_dir, "run.sh", "\n".join(run_sh_lines) + "\n")
    os.chmod(os.path.join(out_dir, "run.sh"), 0o755)

    _log.info("agent.generate", slug=slug, dir=out_dir)

    return {
        "slug": slug,
        "path": out_dir,
        "files": os.listdir(out_dir),
    }


async def list_generated_files(slug: str) -> list[dict[str, Any]]:
    """List all files in the generated agent directory."""
    out_dir = os.path.join(_agents_dir(), slug)
    if not os.path.isdir(out_dir):
        return []
    results: list[dict[str, Any]] = []
    for dirpath, _dirnames, filenames in os.walk(out_dir):
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, out_dir).replace("\\", "/")
            try:
                with open(full_path, encoding="utf-8") as fh:
                    content = fh.read()
            except Exception:
                content = "<binary>"
            results.append({"path": rel_path, "content": content})
    results.sort(key=lambda f: f["path"])
    return results


def _write(directory: str, filename: str, content: str) -> None:
    with open(os.path.join(directory, filename), "w", encoding="utf-8") as f:
        f.write(content)
