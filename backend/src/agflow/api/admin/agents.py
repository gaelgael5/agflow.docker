from __future__ import annotations

import io
import json
import zipfile
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agflow.auth.dependencies import require_admin
from agflow.schemas.agents import (
    AgentCreate,
    AgentDetail,
    AgentProfileCreate,
    AgentProfileSummary,
    AgentProfileUpdate,
    AgentSummary,
    AgentUpdate,
    ConfigPreview,
    DuplicatePayload,
)
from agflow.services import (
    agent_generator,
    agent_profiles_service,
    agents_service,
    composition_builder,
)

router = APIRouter(
    prefix="/api/admin/agents",
    tags=["admin-agents"],
    dependencies=[Depends(require_admin)],
)


@router.get(
    "",
    response_model=list[AgentSummary],
    summary="List all agents",
    description="Returns all registered agents as a list of AgentSummary objects, including their slug, display name, dockerfile, role, and current status.",
)
async def list_agents() -> list[AgentSummary]:
    return await agents_service.list_all()


@router.post(
    "",
    response_model=AgentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create an agent",
    description="Registers a new agent with its dockerfile, role, environment variables, and runtime settings. Returns 201 with the AgentDetail, 409 if the slug already exists, or 400 if a referenced dockerfile or role is invalid.",
)
async def create_agent(payload: AgentCreate) -> AgentDetail:
    try:
        return await agents_service.create(payload)
    except agents_service.DuplicateAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except agents_service.InvalidReferenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get(
    "/assistant",
    response_model=AgentSummary | None,
    summary="Get the designated assistant agent",
    description="Returns the AgentSummary of the agent currently flagged as the platform assistant, or null if none is set.",
)
async def get_assistant() -> AgentSummary | None:
    return await agents_service.get_assistant()


@router.post(
    "/{agent_id}/set-assistant",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set an agent as the assistant",
    description="Designates the specified agent as the platform assistant, clearing the flag from any previously designated agent. Returns 204 on success.",
)
async def set_assistant(agent_id: UUID) -> None:
    await agents_service.set_assistant(agent_id)


@router.delete(
    "/assistant",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear the assistant designation",
    description="Removes the assistant flag from whichever agent currently holds it, leaving no agent designated as assistant. Returns 204 on success.",
)
async def clear_assistant() -> None:
    await agents_service.clear_assistant()


@router.get(
    "/{agent_id}",
    response_model=AgentDetail,
    summary="Get agent detail",
    description="Returns the full AgentDetail for the given agent UUID, including MCP bindings, skill bindings, and mission profiles. Returns 404 if not found.",
)
async def get_agent(agent_id: UUID) -> AgentDetail:
    try:
        return await agents_service.get_by_id(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.put(
    "/{agent_id}",
    response_model=AgentDetail,
    summary="Update an agent",
    description="Partially updates an agent's configuration (display name, dockerfile, role, env vars, runtime settings, bindings). Returns the updated AgentDetail, 404 if not found, or 400 if a referenced resource is invalid.",
)
async def update_agent(agent_id: UUID, payload: AgentUpdate) -> AgentDetail:
    try:
        return await agents_service.update(agent_id, payload)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except agents_service.InvalidReferenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an agent",
    description="Permanently deletes the agent and all its associated profiles, bindings, and generated files. Returns 204 on success, or 404 if the agent does not exist.",
)
async def delete_agent(agent_id: UUID) -> None:
    try:
        await agents_service.delete(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get(
    "/{agent_id}/export",
    summary="Export an agent as a ZIP archive",
    description="Builds an in-memory ZIP containing agent.json (full metadata) and one JSON file per mission profile under profiles/. Streams the result as a download. Returns 404 if the agent does not exist.",
)
async def export_agent(agent_id: UUID) -> StreamingResponse:
    try:
        agent = await agents_service.get_detail(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    profiles = await agents_service.list_profiles(agent_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        meta = {
            "slug": agent.slug,
            "display_name": agent.display_name,
            "description": agent.description,
            "dockerfile_id": agent.dockerfile_id,
            "role_id": agent.role_id,
            "env_vars": agent.env_vars,
            "timeout_seconds": agent.timeout_seconds,
            "workspace_path": agent.workspace_path,
            "network_mode": agent.network_mode,
            "graceful_shutdown_secs": agent.graceful_shutdown_secs,
            "force_kill_delay_secs": agent.force_kill_delay_secs,
            "is_assistant": agent.is_assistant,
            "mcp_bindings": [
                {"catalog_mcp_id": str(b.catalog_mcp_id), "config_overrides": b.config_overrides}
                for b in agent.mcp_bindings
            ],
            "skill_bindings": [
                {"catalog_skill_id": str(b.catalog_skill_id)}
                for b in agent.skill_bindings
            ],
        }
        zf.writestr("agent.json", json.dumps(meta, ensure_ascii=False, indent=2))
        for p in profiles:
            profile_data = {
                "name": p.name,
                "description": p.description,
                "document_ids": [str(d) for d in p.document_ids],
            }
            zf.writestr(f"profiles/{p.name}.json", json.dumps(profile_data, ensure_ascii=False, indent=2))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{agent.slug}.zip"'},
    )


class GeneratePayload(BaseModel):
    profile_id: UUID | None = None
    secrets: dict[str, str] = Field(default_factory=dict)


@router.post(
    "/{agent_id}/generate",
    summary="Generate agent runtime configuration files",
    description="Resolves all secrets, role prompts, and MCP/skill bindings for the agent and writes the resulting configuration files to the agent's workspace. Optionally applies a mission profile. Returns a dict describing the generated files.",
)
async def generate_agent(agent_id: UUID, payload: GeneratePayload | None = None) -> dict:
    try:
        result = await agent_generator.generate(
            agent_id,
            profile_id=payload.profile_id if payload else None,
            user_secrets=payload.secrets if payload and payload.secrets else None,
        )
        return result
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/{agent_id}/generated",
    summary="List generated files for an agent",
    description="Returns a list of file metadata dicts for all files currently present in the agent's generated workspace directory. Returns 404 if the agent does not exist.",
)
async def list_generated_files(agent_id: UUID) -> list[dict]:
    try:
        agent = await agents_service.get_by_id(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await agent_generator.list_generated_files(agent.slug)


@router.delete(
    "/{agent_id}/generated",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete all generated files for an agent",
    description="Recursively removes the entire generated workspace directory for the agent. Idempotent — returns 204 even if the directory does not exist. Returns 404 if the agent does not exist.",
)
async def clean_generated(agent_id: UUID) -> None:
    import os
    import shutil

    try:
        agent = await agents_service.get_by_id(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    gen_dir = os.path.join(
        os.environ.get("AGFLOW_DATA_DIR", "/app/data"),
        "agents", agent.slug, "generated",
    )
    if os.path.isdir(gen_dir):
        shutil.rmtree(gen_dir)


@router.post(
    "/import",
    response_model=AgentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Import an agent from a ZIP archive",
    description="Creates a new agent from a ZIP produced by the export endpoint. Reads agent.json for metadata and profiles/*.json for mission profiles. Returns 201 with the AgentDetail, 400 if the zip or metadata is invalid, or 409 if the slug already exists.",
)
async def import_agent(file: UploadFile = File(...)) -> AgentDetail:
    data = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, "Invalid zip file") from exc

    if "agent.json" not in zf.namelist():
        raise HTTPException(400, "Missing agent.json in zip")

    meta = json.loads(zf.read("agent.json"))
    slug = meta.get("slug", "")
    if not slug:
        raise HTTPException(400, "agent.json missing slug")

    try:
        agent = await agents_service.create(
            slug=slug,
            display_name=meta.get("display_name", slug),
            description=meta.get("description", ""),
            dockerfile_id=meta.get("dockerfile_id", ""),
            role_id=meta.get("role_id", ""),
            env_vars=meta.get("env_vars", {}),
            timeout_seconds=meta.get("timeout_seconds", 600),
            workspace_path=meta.get("workspace_path", ""),
            network_mode=meta.get("network_mode", "bridge"),
            graceful_shutdown_secs=meta.get("graceful_shutdown_secs", 30),
            force_kill_delay_secs=meta.get("force_kill_delay_secs", 10),
        )
    except agents_service.DuplicateAgentError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc

    for info in zf.infolist():
        if not info.filename.startswith("profiles/") or not info.filename.endswith(".json"):
            continue
        try:
            profile_data = json.loads(zf.read(info))
            await agent_profiles_service.create(
                agent.id,
                name=profile_data.get("name", ""),
                description=profile_data.get("description", ""),
                document_ids=[UUID(d) for d in profile_data.get("document_ids", [])],
            )
        except Exception:
            pass

    return await agents_service.get_detail(agent.id)


@router.post(
    "/{agent_id}/duplicate",
    response_model=AgentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate an agent",
    description="Creates a full copy of the agent under a new slug and display name, including its configuration and bindings. Returns 201 with the new AgentDetail, 404 if the source agent does not exist, or 409 if the new slug is already taken.",
)
async def duplicate_agent(
    agent_id: UUID, payload: DuplicatePayload
) -> AgentDetail:
    try:
        return await agents_service.duplicate(
            agent_id, new_slug=payload.slug, new_display_name=payload.display_name
        )
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except agents_service.DuplicateAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get(
    "/{agent_id}/config-preview",
    response_model=ConfigPreview,
    summary="Preview composed agent configuration",
    description="Returns a ConfigPreview showing the fully composed system prompt and environment that would be injected into the agent container at runtime. Optionally applies a mission profile. Returns 404 if the agent or profile does not exist, or 400 if the profile belongs to a different agent.",
)
async def preview_agent_config(
    agent_id: UUID,
    profile_id: UUID | None = Query(
        default=None,
        description="Optional mission profile to apply. Without it, the "
        "prompt is identity-only.",
    ),
) -> ConfigPreview:
    try:
        return await composition_builder.build_preview(agent_id, profile_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except agent_profiles_service.ProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        # Profile belongs to a different agent
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


# ──────────────────────────────────────────────────────────────────
# Mission profiles (NF-3)
# ──────────────────────────────────────────────────────────────────


@router.get(
    "/{agent_id}/profiles",
    response_model=list[AgentProfileSummary],
    summary="List mission profiles for an agent",
    description="Returns all mission profiles associated with the specified agent as a list of AgentProfileSummary objects. Returns 404 if the agent does not exist.",
)
async def list_profiles(agent_id: UUID) -> list[AgentProfileSummary]:
    try:
        await agents_service.get_by_id(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return await agent_profiles_service.list_for_agent(agent_id)


@router.post(
    "/{agent_id}/profiles",
    response_model=AgentProfileSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a mission profile for an agent",
    description="Adds a new mission profile to the specified agent, associating it with a set of role document IDs. Returns 201 with the AgentProfileSummary, 404 if the agent does not exist, or 409 if a profile with the same name already exists.",
)
async def create_profile(
    agent_id: UUID, payload: AgentProfileCreate
) -> AgentProfileSummary:
    try:
        await agents_service.get_by_id(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    try:
        return await agent_profiles_service.create(
            agent_id=agent_id,
            name=payload.name,
            description=payload.description,
            document_ids=payload.document_ids,
        )
    except agent_profiles_service.DuplicateProfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.put(
    "/{agent_id}/profiles/{profile_id}",
    response_model=AgentProfileSummary,
    summary="Update a mission profile",
    description="Updates the name, description, document selection, and optional template settings of the mission profile. Returns the updated AgentProfileSummary, 404 if not found or profile does not belong to the agent, or 409 if the new name conflicts.",
)
async def update_profile(
    agent_id: UUID, profile_id: UUID, payload: AgentProfileUpdate
) -> AgentProfileSummary:
    try:
        existing = await agent_profiles_service.get_by_id(profile_id)
    except agent_profiles_service.ProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    if existing.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile {profile_id} does not belong to agent {agent_id}",
        )
    try:
        return await agent_profiles_service.update(
            profile_id,
            name=payload.name,
            description=payload.description,
            document_ids=payload.document_ids,
            template_slug=payload.template_slug,
            template_culture=payload.template_culture,
        )
    except agent_profiles_service.DuplicateProfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.delete(
    "/{agent_id}/profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a mission profile",
    description="Permanently deletes the specified mission profile. Returns 204 on success, or 404 if the profile does not exist or does not belong to the given agent.",
)
async def delete_profile(agent_id: UUID, profile_id: UUID) -> None:
    try:
        existing = await agent_profiles_service.get_by_id(profile_id)
    except agent_profiles_service.ProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    if existing.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile {profile_id} does not belong to agent {agent_id}",
        )
    await agent_profiles_service.delete(profile_id)
