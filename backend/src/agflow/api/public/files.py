from __future__ import annotations

import base64
from uuid import UUID

from fastapi import APIRouter, status

from agflow.api.public.errors import api_error
from agflow.auth.api_key import require_api_key
from agflow.schemas.dockerfiles import (
    FileCreateBase64,
    FileSummaryBase64,
    FileUpdateBase64,
)
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


def _to_b64(summary) -> FileSummaryBase64:
    return FileSummaryBase64(
        id=summary.id,
        dockerfile_id=summary.dockerfile_id,
        path=summary.path,
        content=base64.b64encode(summary.content.encode("utf-8")).decode("ascii"),
        encoding="base64",
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def _decode_content(b64_content: str | None) -> str | None:
    if b64_content is None:
        return None
    try:
        return base64.b64decode(b64_content).decode("utf-8")
    except Exception as exc:
        raise api_error(
            400, "invalid_base64", f"Content is not valid base64: {exc}"
        ) from exc


@router.get("", response_model=list[FileSummaryBase64])
async def list_files(
    dockerfile_id: str,
    _key: dict = require_api_key("dockerfiles.files:read"),
) -> list[FileSummaryBase64]:
    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    return [_to_b64(f) for f in files]


@router.get("/{file_id}", response_model=FileSummaryBase64)
async def get_file(
    dockerfile_id: str,
    file_id: UUID,
    _key: dict = require_api_key("dockerfiles.files:read"),
) -> FileSummaryBase64:
    try:
        f = await dockerfile_files_service.get_by_id(file_id)
        return _to_b64(f)
    except FileNotFoundError as exc:
        raise api_error(404, "not_found", str(exc)) from exc


@router.post(
    "", response_model=FileSummaryBase64, status_code=status.HTTP_201_CREATED
)
async def create_file(
    dockerfile_id: str,
    payload: FileCreateBase64,
    _key: dict = require_api_key("dockerfiles.files:write"),
) -> FileSummaryBase64:
    content = _decode_content(payload.content) or ""
    try:
        f = await dockerfile_files_service.create(
            dockerfile_id=dockerfile_id,
            path=payload.path,
            content=content,
        )
        return _to_b64(f)
    except DuplicateFileError as exc:
        raise api_error(409, "conflict", str(exc)) from exc


@router.put("/{file_id}", response_model=FileSummaryBase64)
async def update_file(
    dockerfile_id: str,
    file_id: UUID,
    payload: FileUpdateBase64,
    _key: dict = require_api_key("dockerfiles.files:write"),
) -> FileSummaryBase64:
    content = _decode_content(payload.content)
    try:
        f = await dockerfile_files_service.update(
            file_id=file_id,
            content=content,
        )
        return _to_b64(f)
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
