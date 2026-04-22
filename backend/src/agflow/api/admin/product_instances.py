from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.products import InstanceCreate, InstanceSummary, InstanceUpdate
from agflow.services import product_instances_service

router = APIRouter(
    prefix="/api/admin/product-instances",
    tags=["admin-instances"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[InstanceSummary])
async def list_instances(group_id: UUID | None = None, project_id: UUID | None = None):
    if group_id:
        return await product_instances_service.list_by_group(group_id)
    if project_id:
        return await product_instances_service.list_by_project(project_id)
    return await product_instances_service.list_all()


@router.post("", response_model=InstanceSummary, status_code=status.HTTP_201_CREATED)
async def create_instance(payload: InstanceCreate):
    return await product_instances_service.create(
        group_id=payload.group_id,
        instance_name=payload.instance_name,
        catalog_id=payload.catalog_id,
        variables=payload.variables,
    )


@router.get("/{instance_id}", response_model=InstanceSummary)
async def get_instance(instance_id: UUID):
    try:
        return await product_instances_service.get_by_id(instance_id)
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{instance_id}", response_model=InstanceSummary)
async def update_instance(instance_id: UUID, payload: InstanceUpdate):
    try:
        return await product_instances_service.update(instance_id, **payload.model_dump(exclude_unset=True))
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instance(instance_id: UUID):
    try:
        await product_instances_service.delete(instance_id)
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


class ActivateRequest(BaseModel):
    service_url: str


@router.post("/{instance_id}/activate")
async def activate_instance(instance_id: UUID, payload: ActivateRequest):
    try:
        instance = await product_instances_service.update_status(instance_id, "active", payload.service_url)
        return {"instance": instance}
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{instance_id}/stop", response_model=InstanceSummary)
async def stop_instance(instance_id: UUID):
    try:
        return await product_instances_service.update_status(instance_id, "stopped")
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
