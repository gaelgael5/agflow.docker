from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.catalogs import SkillInstallPayload, SkillSummary
from agflow.services import skills_catalog_service

router = APIRouter(
    prefix="/api/admin/skills-catalog",
    tags=["admin-skills-catalog"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[SkillSummary])
async def list_skills() -> list[SkillSummary]:
    return await skills_catalog_service.list_all()


@router.post(
    "", response_model=SkillSummary, status_code=status.HTTP_201_CREATED
)
async def install_skill(payload: SkillInstallPayload) -> SkillSummary:
    try:
        return await skills_catalog_service.install(
            discovery_service_id=payload.discovery_service_id,
            skill_id=payload.skill_id,
        )
    except skills_catalog_service.DuplicateSkillError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.delete("/{skill_uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_uuid: UUID) -> None:
    try:
        await skills_catalog_service.delete(skill_uuid)
    except skills_catalog_service.SkillNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
