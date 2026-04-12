from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from agflow.api.public.errors import api_error
from agflow.auth.api_key import require_api_key
from agflow.schemas.dockerfiles import FileCreate, FileSummary, FileUpdate
from agflow.services import dockerfile_files_service
from agflow.services.dockerfile_files_service import (
    DuplicateFileError,
    FileNotFoundError,
    ProtectedFileError,
)

router = APIRouter(
    prefix="/api/v1/dockerfiles/{dockerfile_id}/files",
    tags=["public-files"],
)


@router.get("", response_model=list[FileSummary])
async def list_files(
    dockerfile_id: str,
    _key: dict = require_api_key("dockerfiles.files:read"),
) -> list[FileSummary]:
    return await dockerfile_files_service.list_for_dockerfile(dockerfile_id)


@router.get("/{file_id}", response_model=FileSummary)
async def get_file(
    dockerfile_id: str,
    file_id: UUID,
    _key: dict = require_api_key("dockerfiles.files:read"),
) -> FileSummary:
    try:
        return await dockerfile_files_service.get_by_id(file_id)
    except FileNotFoundError as exc:
        raise api_error(404, "not_found", str(exc)) from exc


@router.post("", response_model=FileSummary, status_code=status.HTTP_201_CREATED)
async def create_file(
    dockerfile_id: str,
    payload: FileCreate,
    _key: dict = require_api_key("dockerfiles.files:write"),
) -> FileSummary:
    try:
        return await dockerfile_files_service.create(
            dockerfile_id=dockerfile_id,
            path=payload.path,
            content=payload.content,
        )
    except DuplicateFileError as exc:
        raise api_error(409, "conflict", str(exc)) from exc


@router.put("/{file_id}", response_model=FileSummary)
async def update_file(
    dockerfile_id: str,
    file_id: UUID,
    payload: FileUpdate,
    _key: dict = require_api_key("dockerfiles.files:write"),
) -> FileSummary:
    try:
        return await dockerfile_files_service.update(
            file_id=file_id,
            content=payload.content,
        )
    except FileNotFoundError as exc:
        raise api_error(404, "not_found", str(exc)) from exc
    except ProtectedFileError as exc:
        raise api_error(403, "forbidden", str(exc)) from exc


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    dockerfile_id: str,
    file_id: UUID,
    _key: dict = require_api_key("dockerfiles.files:delete"),
) -> None:
    try:
        await dockerfile_files_service.delete(file_id)
    except FileNotFoundError as exc:
        raise api_error(404, "not_found", str(exc)) from exc
    except ProtectedFileError as exc:
        raise api_error(403, "forbidden", str(exc)) from exc
