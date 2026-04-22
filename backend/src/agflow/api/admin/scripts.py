from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.scripts import (
    ScriptCreate,
    ScriptRow,
    ScriptSummary,
    ScriptUpdate,
)
from agflow.services import scripts_service

router = APIRouter(
    prefix="/api/admin/scripts",
    tags=["admin-scripts"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[ScriptSummary])
async def list_scripts():
    return await scripts_service.list_all()


@router.post("", response_model=ScriptRow, status_code=status.HTTP_201_CREATED)
async def create_script(payload: ScriptCreate):
    try:
        return await scripts_service.create(
            name=payload.name.strip(),
            description=payload.description,
            content=payload.content,
            execute_on_types_named=payload.execute_on_types_named,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{script_id}", response_model=ScriptRow)
async def get_script(script_id: UUID):
    try:
        return await scripts_service.get_by_id(script_id)
    except scripts_service.ScriptNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{script_id}", response_model=ScriptRow)
async def update_script(script_id: UUID, payload: ScriptUpdate):
    try:
        return await scripts_service.update(
            script_id, **payload.model_dump(exclude_unset=True),
        )
    except scripts_service.ScriptNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{script_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_script(script_id: UUID):
    try:
        await scripts_service.delete(script_id)
    except scripts_service.ScriptNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
