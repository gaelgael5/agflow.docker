from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.products import ProjectCreate, ProjectSummary, ProjectUpdate
from agflow.services import groups_service, product_instances_service, projects_service

router = APIRouter(
    prefix="/api/admin/projects",
    tags=["admin-projects"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[ProjectSummary])
async def list_projects():
    return await projects_service.list_all()


@router.post("", response_model=ProjectSummary, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate):
    return await projects_service.create(
        display_name=payload.display_name,
        description=payload.description,
        tags=payload.tags,
        network=payload.network,
    )


@router.get("/{project_id}", response_model=ProjectSummary)
async def get_project(project_id: UUID):
    try:
        return await projects_service.get_by_id(project_id)
    except projects_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{project_id}", response_model=ProjectSummary)
async def update_project(project_id: UUID, payload: ProjectUpdate):
    try:
        return await projects_service.update(project_id, **payload.model_dump(exclude_unset=True))
    except projects_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{project_id}/full")
async def get_project_full(project_id: UUID):
    """Return project with all groups and their instances."""
    try:
        project = await projects_service.get_by_id(project_id)
    except projects_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    groups = await groups_service.list_by_project(project_id)
    groups_out = []
    for g in groups:
        instances = await product_instances_service.list_by_group(g.id)
        groups_out.append({
            "id": str(g.id),
            "name": g.name,
            "max_agents": g.max_agents,
            "instances": [
                {
                    "id": str(i.id),
                    "instance_name": i.instance_name,
                    "catalog_id": i.catalog_id,
                    "variables": i.variables,
                    "status": i.status,
                    "service_url": i.service_url,
                }
                for i in instances
            ],
        })

    return {
        "id": str(project.id),
        "display_name": project.display_name,
        "description": project.description,
        "groups": groups_out,
    }


@router.get("/list/full")
async def list_projects_full():
    """Return all projects with groups and instances."""
    projects = await projects_service.list_all()
    result = []
    for project in projects:
        groups = await groups_service.list_by_project(project.id)
        groups_out = []
        for g in groups:
            instances = await product_instances_service.list_by_group(g.id)
            groups_out.append({
                "id": str(g.id),
                "name": g.name,
                "max_agents": g.max_agents,
                "instances": [
                    {
                        "id": str(i.id),
                        "instance_name": i.instance_name,
                        "catalog_id": i.catalog_id,
                        "variables": i.variables,
                        "status": i.status,
                    }
                    for i in instances
                ],
            })
        result.append({
            "id": str(project.id),
            "display_name": project.display_name,
            "description": project.description,
            "groups": groups_out,
        })
    return result


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: UUID):
    try:
        await projects_service.delete(project_id)
    except projects_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Endpoints v5 contract-shaped (workflow contracts) ─────────────

from agflow.schemas.workflow import ProjectSummaryV5, ResourceSummary  # noqa: E402


@router.get("/v5/list", response_model=list[ProjectSummaryV5])
async def list_projects_v5() -> list[ProjectSummaryV5]:
    """Endpoint v5 contract-shaped : liste avec resources_summary."""
    projects = await projects_service.list_all()
    result: list[ProjectSummaryV5] = []
    for p in projects:
        groups = await groups_service.list_by_project(p.id)
        resources_summary: list[ResourceSummary] = []
        for g in groups:
            instances = await product_instances_service.list_by_group(g.id)
            for i in instances:
                resources_summary.append(
                    ResourceSummary(type=i.catalog_id, label=i.instance_name)
                )
        result.append(
            ProjectSummaryV5(
                project_id=p.id,
                name=p.display_name,
                description=p.description,
                resources_summary=resources_summary,
            )
        )
    return result


@router.get("/v5/{project_id}", response_model=ProjectSummaryV5)
async def get_project_v5(project_id: UUID) -> ProjectSummaryV5:
    """Endpoint v5 contract-shaped : détail avec resources_summary."""
    try:
        project = await projects_service.get_by_id(project_id)
    except projects_service.ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    groups = await groups_service.list_by_project(project.id)
    resources_summary: list[ResourceSummary] = []
    for g in groups:
        instances = await product_instances_service.list_by_group(g.id)
        for i in instances:
            resources_summary.append(
                ResourceSummary(type=i.catalog_id, label=i.instance_name)
            )
    return ProjectSummaryV5(
        project_id=project.id,
        name=project.display_name,
        description=project.description,
        resources_summary=resources_summary,
    )
