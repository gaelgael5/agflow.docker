from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.products import (
    InstanceCreate,
    InstanceSummary,
    InstanceUpdate,
)
from agflow.services import activation_service, product_backends_service, product_instances_service

router = APIRouter(
    prefix="/api/admin/product-instances",
    tags=["admin-instances"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[InstanceSummary])
async def list_instances(project_id: str | None = None):
    if project_id:
        return product_instances_service.list_for_project(project_id)
    return product_instances_service.list_all()


@router.post("", response_model=InstanceSummary, status_code=status.HTTP_201_CREATED)
async def create_instance(payload: InstanceCreate):
    try:
        return product_instances_service.create(
            instance_name=payload.instance_name,
            catalog_id=payload.catalog_id,
            project_id=payload.project_id,
            variables=payload.variables,
            secret_refs=payload.secret_refs,
            service_role=payload.service_role,
        )
    except product_instances_service.DuplicateInstanceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{project_id}/{instance_id}", response_model=InstanceSummary)
async def get_instance(project_id: str, instance_id: str):
    try:
        return product_instances_service.get_by_id(project_id, instance_id)
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{project_id}/{instance_id}", response_model=InstanceSummary)
async def update_instance(project_id: str, instance_id: str, payload: InstanceUpdate):
    try:
        return product_instances_service.update(
            project_id, instance_id, **payload.model_dump(exclude_unset=True),
        )
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{project_id}/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instance(project_id: str, instance_id: str):
    try:
        product_instances_service.delete(project_id, instance_id)
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


class ActivateRequest(BaseModel):
    service_url: str


@router.post("/{project_id}/{instance_id}/activate")
async def activate_instance(project_id: str, instance_id: str, payload: ActivateRequest):
    try:
        backend = await activation_service.activate(project_id, instance_id, payload.service_url)
        instance = product_instances_service.get_by_id(project_id, instance_id)
        return {"instance": instance, "backend": backend}
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{project_id}/{instance_id}/stop", response_model=InstanceSummary)
async def stop_instance(project_id: str, instance_id: str):
    try:
        await activation_service.deactivate(project_id, instance_id)
        return product_instances_service.get_by_id(project_id, instance_id)
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{project_id}/{instance_id}/refresh-openapi")
async def refresh_openapi(project_id: str, instance_id: str):
    try:
        backend = await activation_service.refresh_openapi(project_id, instance_id)
        return {"status": backend.get("status"), "openapi_fetched": backend.get("openapi_fetched")}
    except product_backends_service.BackendNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/{project_id}/{instance_id}/backend")
async def get_backend(project_id: str, instance_id: str):
    backend = product_backends_service.get(project_id, instance_id)
    if not backend:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No backend for this instance")
    return backend
