from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from agflow.auth.dependencies import require_admin
from agflow.db.pool import fetch_all, fetch_one
from agflow.schemas.infra import TypeRow
from agflow.services import types_loader

router = APIRouter(prefix="/api/infra/types", tags=["infra-types"])


@router.get("", response_model=list[TypeRow], dependencies=[Depends(require_admin)])
async def list_types(type: str | None = None):
    if type:
        rows = await fetch_all(
            "SELECT name, type FROM infra_types WHERE type = $1 ORDER BY name", type,
        )
    else:
        rows = await fetch_all("SELECT name, type FROM infra_types ORDER BY type, name")
    return [TypeRow(**r) for r in rows]


class TypeCreate(BaseModel):
    name: str
    type: str


@router.post("", response_model=TypeRow, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_type(payload: TypeCreate):
    if payload.type not in ("platform", "service"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="type must be 'platform' or 'service'")
    try:
        row = await fetch_one(
            "INSERT INTO infra_types (name, type) VALUES ($1, $2) RETURNING name, type",
            payload.name, payload.type,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    assert row is not None
    return TypeRow(**row)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_type(name: str):
    from agflow.db.pool import execute
    try:
        result = await execute("DELETE FROM infra_types WHERE name = $1", name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Impossible de supprimer '{name}' — utilisé par des serveurs ou machines",
        ) from exc
    if result.endswith(" 0"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Type '{name}' not found")


@router.post("/reload", dependencies=[Depends(require_admin)])
async def reload_types():
    counts = types_loader.reload()
    return {"status": "ok", **counts}
