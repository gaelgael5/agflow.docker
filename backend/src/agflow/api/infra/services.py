from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from agflow.auth.dependencies import require_admin
from agflow.schemas.infra import ServiceDef
from agflow.services import types_loader

router = APIRouter(
    prefix="/api/infra/services",
    tags=["infra-services"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[ServiceDef])
async def list_services():
    return types_loader.get_services()


@router.get("/{name}", response_model=ServiceDef)
async def get_service(name: str):
    s = types_loader.get_service(name)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Service '{name}' not found")
    return s


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1)
    type: str = ""
    connection: str = "SSH"
    scripts: list[str] = Field(default_factory=list)


@router.post("", response_model=ServiceDef, status_code=status.HTTP_201_CREATED)
async def create_service(payload: ServiceCreate):
    if types_loader.get_service(payload.name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Service '{payload.name}' already exists")
    sdef = ServiceDef(
        name=payload.name,
        type=payload.type,
        connection=payload.connection,
        scripts=payload.scripts,
    )
    types_loader.save_service(sdef)
    return sdef


@router.put("/{name}", response_model=ServiceDef)
async def update_service(name: str, payload: ServiceCreate):
    if not types_loader.get_service(name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Service '{name}' not found")
    if payload.name != name:
        types_loader.delete_service(name)
    sdef = ServiceDef(
        name=payload.name,
        type=payload.type,
        connection=payload.connection,
        scripts=payload.scripts,
    )
    types_loader.save_service(sdef)
    return sdef


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(name: str):
    if not types_loader.get_service(name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Service '{name}' not found")
    types_loader.delete_service(name)
