from __future__ import annotations

from uuid import UUID

import structlog

from agflow.schemas.agents import ConfigPreview, SkillPreview
from agflow.schemas.roles import DocumentSummary
from agflow.services import (
    agent_profiles_service,
    agents_service,
    mcp_catalog_service,
    prompt_generator,
    role_sections_service,
    roles_service,
    secrets_service,
    skills_catalog_service,
)

_log = structlog.get_logger(__name__)


async def _compile_prompt_identity_only(role_id: str) -> str:
    """Assemble identity only — no documents.

    This is the default behavior: an agent instantiated without a profile
    receives only the role identity in its system prompt, keeping the prompt
    minimal and unbiased toward any specific mission.
    """
    role = await roles_service.get_by_id(role_id)
    # Passing [] for documents yields just the identity block.
    return prompt_generator.assemble_source_markdown(role, [], None)


async def _compile_prompt_with_profile(
    role_id: str, profile_document_ids: list[UUID]
) -> tuple[str, list[UUID]]:
    """Assemble identity + the documents referenced by the profile.

    Documents that don't exist anymore (e.g. deleted from the role, or from
    a previous role of the agent) are reported back as missing UUIDs so the
    caller can flag the agent as in-error.
    """
    role = await roles_service.get_by_id(role_id)
    sections = await role_sections_service.list_for_role(role_id)

    found_rows, missing = await agent_profiles_service.resolve_documents(
        profile_document_ids
    )
    documents = [DocumentSummary(**row) for row in found_rows]
    prompt = prompt_generator.assemble_source_markdown(role, documents, sections)
    return prompt, missing


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


async def build_preview(
    agent_id: UUID, profile_id: UUID | None = None
) -> ConfigPreview:
    """Assemble the agent's runtime config preview.

    - Without `profile_id`: the prompt is **identity-only** (minimal).
    - With `profile_id`: the prompt is identity + the documents picked
      by that profile. Any referenced document that no longer exists is
      reported as a broken ref in `broken_document_ids`, added to
      `validation_errors`, and flags the agent as in-error.
    """
    agent = await agents_service.get_by_id(agent_id)
    validation_errors: list[str] = []
    profile_name: str | None = None
    broken_document_ids: list[UUID] = []

    if profile_id is None:
        prompt_md = await _compile_prompt_identity_only(agent.role_id)
    else:
        profile = await agent_profiles_service.get_by_id(profile_id)
        if profile.agent_id != agent_id:
            raise ValueError(
                f"Profile {profile_id} does not belong to agent {agent_id}"
            )
        profile_name = profile.name
        prompt_md, broken_document_ids = await _compile_prompt_with_profile(
            agent.role_id, profile.document_ids
        )
        if broken_document_ids:
            validation_errors.append(
                f"Profile '{profile.name}' references "
                f"{len(broken_document_ids)} missing document(s). The agent's "
                f"role may have changed or these documents were deleted."
            )

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
        profile_id=str(profile_id) if profile_id else None,
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
        profile_name=profile_name,
        broken_document_ids=broken_document_ids,
    )
