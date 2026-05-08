from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from agflow.auth.dependencies import require_operator as require_admin
from agflow.db.pool import fetch_all
from agflow.schemas.templates import (
    FileCreate,
    FileUpdate,
    TemplateCreate,
    TemplateDetail,
    TemplateSummary,
    TemplateUpdate,
)
from agflow.services import template_storage_service
from agflow.services.template_storage_service import (
    DuplicateTemplateError,
    TemplateFileNotFoundError,
    TemplateNotFoundError,
)

router = APIRouter(
    prefix="/api/admin/templates",
    tags=["admin-templates"],
    dependencies=[Depends(require_admin)],
)


class TemplateCulture(BaseModel):
    key: str
    label: str
    sort_order: int


@router.get("/cultures", response_model=list[TemplateCulture])
async def list_cultures():
    rows = await fetch_all(
        "SELECT key, label, sort_order FROM template_cultures ORDER BY sort_order"
    )
    return [TemplateCulture(**dict(r)) for r in rows]


@router.get("", response_model=list[TemplateSummary])
async def list_templates():
    return await template_storage_service.list_all()


@router.post("", response_model=TemplateSummary, status_code=status.HTTP_201_CREATED)
async def create_template(payload: TemplateCreate):
    try:
        return await template_storage_service.create(
            payload.slug, payload.display_name, payload.description
        )
    except DuplicateTemplateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{slug}", response_model=TemplateDetail)
async def get_template(slug: str):
    try:
        return await template_storage_service.get_detail(slug)
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{slug}", response_model=TemplateSummary)
async def update_template(slug: str, payload: TemplateUpdate):
    try:
        return await template_storage_service.update(
            slug, display_name=payload.display_name, description=payload.description
        )
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(slug: str):
    try:
        await template_storage_service.delete(slug)
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{slug}/files", status_code=status.HTTP_201_CREATED)
async def create_file(slug: str, payload: FileCreate):
    await template_storage_service.write_file(slug, payload.filename, payload.content)
    return {"filename": payload.filename}


@router.get("/{slug}/files/{filename}")
async def get_file(slug: str, filename: str):
    try:
        content = await template_storage_service.read_file(slug, filename)
    except TemplateFileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"filename": filename, "content": content}


@router.put("/{slug}/files/{filename}")
async def update_file(slug: str, filename: str, payload: FileUpdate):
    await template_storage_service.write_file(slug, filename, payload.content)
    return {"filename": filename}


@router.delete("/{slug}/files/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(slug: str, filename: str):
    try:
        await template_storage_service.delete_file(slug, filename)
    except TemplateFileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
