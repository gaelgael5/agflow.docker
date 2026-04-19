from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.products import (
    ProjectCreate,
    ProjectSummary,
    ProjectUpdate,
)
from agflow.services import projects_service

router = APIRouter(
    prefix="/api/admin/projects",
    tags=["admin-projects"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[ProjectSummary])
async def list_projects():
    return projects_service.list_all()


@router.post("", response_model=ProjectSummary, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate):
    try:
        return projects_service.create(
            project_id=payload.id,
            display_name=payload.display_name,
            description=payload.description,
            environment=payload.environment,
            tags=payload.tags,
        )
    except projects_service.DuplicateProjectError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{project_id}", response_model=ProjectSummary)
async def get_project(project_id: str):
    try:
        return projects_service.get_by_id(project_id)
    except projects_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{project_id}", response_model=ProjectSummary)
async def update_project(project_id: str, payload: ProjectUpdate):
    try:
        return projects_service.update(project_id, **payload.model_dump(exclude_unset=True))
    except projects_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str):
    try:
        projects_service.delete(project_id)
    except projects_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
