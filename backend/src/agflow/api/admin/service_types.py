from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.service_types import ServiceTypeCreate, ServiceTypeSummary
from agflow.services import service_types_service

router = APIRouter(
    prefix="/api/admin/service-types",
    tags=["admin-service-types"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[ServiceTypeSummary])
async def list_service_types() -> list[ServiceTypeSummary]:
    return await service_types_service.list_all()


@router.post(
    "",
    response_model=ServiceTypeSummary,
    status_code=status.HTTP_201_CREATED,
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


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
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
