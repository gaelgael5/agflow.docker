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


@router.get("", response_model=list[AgentSummary])
async def list_agents() -> list[AgentSummary]:
    return await agents_service.list_all()


@router.post("", response_model=AgentDetail, status_code=status.HTTP_201_CREATED)
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


@router.get("/assistant", response_model=AgentSummary | None)
async def get_assistant() -> AgentSummary | None:
    return await agents_service.get_assistant()


@router.post("/{agent_id}/set-assistant", status_code=status.HTTP_204_NO_CONTENT)
async def set_assistant(agent_id: UUID) -> None:
    await agents_service.set_assistant(agent_id)


@router.delete("/assistant", status_code=status.HTTP_204_NO_CONTENT)
async def clear_assistant() -> None:
    await agents_service.clear_assistant()


@router.get("/{agent_id}", response_model=AgentDetail)
async def get_agent(agent_id: UUID) -> AgentDetail:
    try:
        return await agents_service.get_by_id(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.put("/{agent_id}", response_model=AgentDetail)
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


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: UUID) -> None:
    try:
        await agents_service.delete(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get("/{agent_id}/export")
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


@router.post("/{agent_id}/generate")
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


@router.get("/{agent_id}/generated")
async def list_generated_files(agent_id: UUID) -> list[dict]:
    try:
        agent = await agents_service.get_by_id(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await agent_generator.list_generated_files(agent.slug)


@router.post("/import", response_model=AgentDetail, status_code=status.HTTP_201_CREATED)
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


@router.get("/{agent_id}/config-preview", response_model=ConfigPreview)
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
    "/{agent_id}/profiles", response_model=list[AgentProfileSummary]
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
        )
    except agent_profiles_service.DuplicateProfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.delete(
    "/{agent_id}/profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
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


