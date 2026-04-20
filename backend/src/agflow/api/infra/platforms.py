from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.infra import PlatformDef
from agflow.services import types_loader

router = APIRouter(
    prefix="/api/infra/platforms",
    tags=["infra-platforms"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[PlatformDef])
async def list_platforms():
    return types_loader.get_platforms()


@router.get("/{name}", response_model=PlatformDef)
async def get_platform(name: str):
    p = types_loader.get_platform(name)
    if p is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Platform '{name}' not found")
    return p


class PlatformCreate(BaseModel):
    name: str = Field(min_length=1)
    type: str = ""
    service: str = Field(min_length=1)
    connection: str = "SSH"
    scripts: dict[str, list[str]] = Field(default_factory=dict)


@router.post("", response_model=PlatformDef, status_code=status.HTTP_201_CREATED)
async def create_platform(payload: PlatformCreate):
    if types_loader.get_platform(payload.name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Platform '{payload.name}' already exists")
    pdef = PlatformDef(
        name=payload.name,
        type=payload.type,
        service=payload.service,
        connection=payload.connection,
        scripts=payload.scripts,
    )
    types_loader.save_platform(pdef)
    return pdef


@router.put("/{name}", response_model=PlatformDef)
async def update_platform(name: str, payload: PlatformCreate):
    if not types_loader.get_platform(name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Platform '{name}' not found")
    # If name changed, delete old
    if payload.name != name:
        types_loader.delete_platform(name)
    pdef = PlatformDef(
        name=payload.name,
        type=payload.type,
        service=payload.service,
        connection=payload.connection,
        scripts=payload.scripts,
    )
    types_loader.save_platform(pdef)
    return pdef


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_platform(name: str):
    if not types_loader.get_platform(name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Platform '{name}' not found")
    types_loader.delete_platform(name)
