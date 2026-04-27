"""Public read-only API for the project catalogue.

Lets a SaaS owner discover the projects (blueprints) they can instantiate
into a runtime. Projects themselves are global (no owner) — only runtimes
are user-scoped, and that's handled in api/public/runtimes.py.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from agflow.auth.api_key import require_api_key
from agflow.schemas.runtimes_public import (
    ProjectDetailPublic,
    ProjectGroupOut,
    ProjectSummaryPublic,
)
from agflow.services import groups_service, projects_service

router = APIRouter(prefix="/api/v1", tags=["public-projects"])


@router.get("/projects", response_model=list[ProjectSummaryPublic])
async def list_projects(
    _key: dict = require_api_key("projects:read"),  # noqa: B008
) -> list[ProjectSummaryPublic]:
    rows = await projects_service.list_all()
    return [
        ProjectSummaryPublic(
            id=r.id,
            display_name=r.display_name,
            description=r.description,
            tags=r.tags,
            group_count=r.group_count,
        )
        for r in rows
    ]


@router.get("/projects/{project_id}", response_model=ProjectDetailPublic)
async def get_project(
    project_id: UUID,
    _key: dict = require_api_key("projects:read"),  # noqa: B008
) -> ProjectDetailPublic:
    try:
        project = await projects_service.get_by_id(project_id)
    except projects_service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    groups = await groups_service.list_by_project(project_id)
    return ProjectDetailPublic(
        id=project.id,
        display_name=project.display_name,
        description=project.description,
        tags=project.tags,
        group_count=project.group_count,
        groups=[
            ProjectGroupOut(
                id=g.id,
                name=g.name,
                max_replicas=g.max_replicas,
                instance_count=g.instance_count,
            )
            for g in groups
        ],
    )
