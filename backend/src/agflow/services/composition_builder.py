from __future__ import annotations

from uuid import UUID

import structlog

from agflow.schemas.agents import ConfigPreview, SkillPreview
from agflow.services import (
    agents_service,
    mcp_catalog_service,
    prompt_generator,
    role_documents_service,
    role_sections_service,
    roles_service,
    secrets_service,
    skills_catalog_service,
)

_log = structlog.get_logger(__name__)


async def _compile_prompt(role_id: str) -> str:
    role = await roles_service.get_by_id(role_id)
    documents = await role_documents_service.list_for_role(role_id)
    sections = await role_sections_service.list_for_role(role_id)
    return prompt_generator.assemble_source_markdown(role, documents, sections)


async def _build_mcp_section(
    bindings: list,
) -> tuple[dict, list[dict]]:
    mcp_servers: dict[str, dict] = {}
    tools: list[dict] = []
    for binding in bindings:
        mcp = await mcp_catalog_service.get_by_id(binding.mcp_server_id)
        merged = {**mcp.parameters, **binding.parameters_override}
        mcp_servers[mcp.name] = {
            "package_id": mcp.package_id,
            "repo": mcp.repo,
            "transport": mcp.transport,
            "parameters": merged,
        }
        tools.append(
            {
                "name": mcp.name,
                "type": "mcp",
                "source": mcp.name,
                "description": mcp.short_description or mcp.name,
            }
        )
    return {"mcpServers": mcp_servers}, tools


async def _collect_skills(bindings: list) -> list[SkillPreview]:
    out: list[SkillPreview] = []
    for binding in bindings:
        skill = await skills_catalog_service.get_by_id(binding.skill_id)
        out.append(
            SkillPreview(
                skill_id=skill.id, name=skill.name, content_md=skill.content_md
            )
        )
    return out


async def _resolve_env(
    env_vars: dict[str, str],
) -> tuple[str, list[str]]:
    needed: list[str] = []
    for value in env_vars.values():
        if isinstance(value, str) and value.startswith("$"):
            needed.append(value[1:])

    resolved: dict[str, str] = {}
    errors: list[str] = []
    if needed:
        try:
            resolved = await secrets_service.resolve_env(needed)
        except secrets_service.SecretNotFoundError as exc:
            errors.append(str(exc))
            # Best-effort: resolve individually so partial success is visible
            for name in needed:
                try:
                    got = await secrets_service.resolve_env([name])
                    resolved.update(got)
                except secrets_service.SecretNotFoundError:
                    pass

    lines: list[str] = []
    for key, raw_value in env_vars.items():
        if isinstance(raw_value, str) and raw_value.startswith("$"):
            secret_name = raw_value[1:]
            if secret_name in resolved:
                lines.append(f"{key}={resolved[secret_name]}")
            else:
                lines.append(f"{key}=<missing>")
                if not any(secret_name in e for e in errors):
                    errors.append(f"Missing secret: {secret_name}")
        else:
            lines.append(f"{key}={raw_value}")
    return "\n".join(lines), errors


async def build_preview(agent_id: UUID) -> ConfigPreview:
    agent = await agents_service.get_by_id(agent_id)
    validation_errors: list[str] = []

    prompt_md = await _compile_prompt(agent.role_id)
    mcp_json, tools_json = await _build_mcp_section(agent.mcp_bindings)
    skills = await _collect_skills(agent.skill_bindings)
    env_file, env_errors = await _resolve_env(agent.env_vars)
    validation_errors.extend(env_errors)

    if agent.image_status == "missing":
        validation_errors.append(
            "Docker image not built. Run a build in Module 1."
        )
    elif agent.image_status == "stale":
        validation_errors.append(
            "Docker image is stale. Rebuild in Module 1."
        )

    _log.info(
        "composition.preview",
        agent_id=str(agent_id),
        errors=len(validation_errors),
    )
    return ConfigPreview(
        prompt_md=prompt_md,
        mcp_json=mcp_json,
        tools_json=tools_json,
        env_file=env_file,
        skills=skills,
        validation_errors=validation_errors,
        image_status=agent.image_status,
    )
