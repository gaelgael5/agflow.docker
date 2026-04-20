from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.service_types import ServiceTypeCreate, ServiceTypeSummary
from agflow.services import service_types_service

router = APIRouter(
    prefix="/api/admin/service-types",
    tags=["admin-service-types"],
    dependencies=[Depends(require_admin)],
)


@router.get(
    "",
    response_model=list[ServiceTypeSummary],
    summary="List all service types",
    description="Returns all registered agent service types (e.g. claude-code, aider, codex) available for use in compositions.",
)
async def list_service_types() -> list[ServiceTypeSummary]:
    return await service_types_service.list_all()


@router.post(
    "",
    response_model=ServiceTypeSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new service type",
    description="Creates a new agent service type with a unique slug name and a human-readable display name. Returns 409 if the name is already taken.",
)
async def create_service_type(
    payload: ServiceTypeCreate,
) -> ServiceTypeSummary:
    try:
        return await service_types_service.create(
            name=payload.name, display_name=payload.display_name
        )
    except service_types_service.DuplicateServiceTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.delete(
    "/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a service type",
    description="Removes a service type by slug name. Returns 403 if the type is protected, 404 if not found, or 409 if it is still referenced by existing compositions.",
)
async def delete_service_type(name: str) -> None:
    try:
        await service_types_service.delete(name)
    except service_types_service.ServiceTypeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except service_types_service.ProtectedServiceTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except service_types_service.ServiceTypeInUseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
