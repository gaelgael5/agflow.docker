from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.templates import (
    FileCreate,
    FileUpdate,
    TemplateCreate,
    TemplateDetail,
    TemplateSummary,
    TemplateUpdate,
)
from agflow.services import template_files_service

router = APIRouter(
    prefix="/api/admin/templates",
    tags=["admin-templates"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[TemplateSummary])
async def list_templates():
    return template_files_service.list_all()


@router.post("", response_model=TemplateSummary, status_code=status.HTTP_201_CREATED)
async def create_template(payload: TemplateCreate):
    try:
        return template_files_service.create(
            payload.slug, payload.display_name, payload.description
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{slug}", response_model=TemplateDetail)
async def get_template(slug: str):
    try:
        return template_files_service.get_detail(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{slug}", response_model=TemplateSummary)
async def update_template(slug: str, payload: TemplateUpdate):
    try:
        return template_files_service.update(
            slug, display_name=payload.display_name, description=payload.description
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(slug: str):
    try:
        template_files_service.delete(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{slug}/files", status_code=status.HTTP_201_CREATED)
async def create_file(slug: str, payload: FileCreate):
    template_files_service.write_file(slug, payload.filename, payload.content)
    return {"filename": payload.filename}


@router.get("/{slug}/files/{filename}")
async def get_file(slug: str, filename: str):
    try:
        content = template_files_service.read_file(slug, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"filename": filename, "content": content}


@router.put("/{slug}/files/{filename}")
async def update_file(slug: str, filename: str, payload: FileUpdate):
    template_files_service.write_file(slug, filename, payload.content)
    return {"filename": filename}


@router.delete("/{slug}/files/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(slug: str, filename: str):
    try:
        template_files_service.delete_file(slug, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
