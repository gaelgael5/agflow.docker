from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from agflow.auth.dependencies import require_admin
from agflow.schemas.dockerfiles import (
    BuildSummary,
    DockerfileCreate,
    DockerfileDetail,
    DockerfileSummary,
    DockerfileUpdate,
    FileCreate,
    FileSummary,
    FileUpdate,
)
from agflow.services import (
    build_service,
    dockerfile_chat_service,
    dockerfile_files_service,
    dockerfiles_service,
)


class ChatGenerateRequest(BaseModel):
    description: str = Field(min_length=10, max_length=4000)

router = APIRouter(
    prefix="/api/admin/dockerfiles",
    tags=["admin-dockerfiles"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[DockerfileSummary])
async def list_dockerfiles() -> list[DockerfileSummary]:
    return await dockerfiles_service.list_all()


@router.post(
    "", response_model=DockerfileSummary, status_code=status.HTTP_201_CREATED
)
async def create_dockerfile(payload: DockerfileCreate) -> DockerfileSummary:
    try:
        return await dockerfiles_service.create(
            dockerfile_id=payload.id,
            display_name=payload.display_name,
            description=payload.description,
            parameters=payload.parameters,
        )
    except dockerfiles_service.DuplicateDockerfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get("/{dockerfile_id}", response_model=DockerfileDetail)
async def get_dockerfile(dockerfile_id: str) -> DockerfileDetail:
    try:
        dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    return DockerfileDetail(dockerfile=dockerfile, files=files)


@router.put("/{dockerfile_id}", response_model=DockerfileSummary)
async def update_dockerfile(
    dockerfile_id: str, payload: DockerfileUpdate
) -> DockerfileSummary:
    try:
        return await dockerfiles_service.update(
            dockerfile_id,
            **payload.model_dump(exclude_unset=True),
        )
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete("/{dockerfile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dockerfile(dockerfile_id: str) -> None:
    try:
        await dockerfiles_service.delete(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/{dockerfile_id}/files",
    response_model=FileSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_file(dockerfile_id: str, payload: FileCreate) -> FileSummary:
    try:
        return await dockerfile_files_service.create(
            dockerfile_id=dockerfile_id,
            path=payload.path,
            content=payload.content,
        )
    except dockerfile_files_service.DuplicateFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.put("/{dockerfile_id}/files/{file_id}", response_model=FileSummary)
async def update_file(
    dockerfile_id: str, file_id: UUID, payload: FileUpdate
) -> FileSummary:
    try:
        return await dockerfile_files_service.update(
            file_id, content=payload.content
        )
    except dockerfile_files_service.FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete(
    "/{dockerfile_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_file(dockerfile_id: str, file_id: UUID) -> None:
    try:
        await dockerfile_files_service.delete(file_id)
    except dockerfile_files_service.FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except dockerfile_files_service.ProtectedFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc


@router.post(
    "/{dockerfile_id}/build",
    response_model=BuildSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_build(
    dockerfile_id: str, background: BackgroundTasks
) -> BuildSummary:
    try:
        dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    tag = build_service.image_tag_for(dockerfile_id, dockerfile.current_hash)
    build_id = await build_service.create_build_row(
        dockerfile_id=dockerfile_id,
        content_hash=dockerfile.current_hash,
        tag=tag,
    )

    background.add_task(_run_build_in_background, build_id, dockerfile_id, tag)

    row = await build_service.get_build(build_id)
    assert row is not None
    return BuildSummary(**row)


async def _run_build_in_background(
    build_id: UUID, dockerfile_id: str, tag: str
) -> None:
    """Wrapper to swallow exceptions from the background task."""
    try:
        await build_service.run_build(build_id, dockerfile_id, tag)
    except Exception:
        import structlog

        structlog.get_logger(__name__).exception(
            "build.background.error", build_id=str(build_id)
        )


@router.get("/{dockerfile_id}/builds", response_model=list[BuildSummary])
async def list_builds(dockerfile_id: str) -> list[BuildSummary]:
    rows = await build_service.list_builds(dockerfile_id)
    return [BuildSummary(**r) for r in rows]


@router.get(
    "/{dockerfile_id}/builds/{build_id}", response_model=BuildSummary
)
async def get_build(dockerfile_id: str, build_id: UUID) -> BuildSummary:
    row = await build_service.get_build(build_id)
    if row is None or row["dockerfile_id"] != dockerfile_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Build not found"
        )
    return BuildSummary(**row)


# ──────────────────────────────────────────────────────────────────────
# Chat-assisted Dockerfile generation (NF-1)
# ──────────────────────────────────────────────────────────────────────


@router.post("/chat-generate")
async def chat_generate_dockerfile(
    payload: ChatGenerateRequest,
) -> dockerfile_chat_service.GeneratedDockerfile:
    """Generate Dockerfile + entrypoint.sh + run.cmd.md from a natural
    language description via Anthropic Claude. Stateless — the client is
    expected to show the result, let the user approve, and then create
    the dockerfile via the regular POST endpoint.
    """
    try:
        return await dockerfile_chat_service.generate(payload.description)
    except dockerfile_chat_service.MissingAnthropicKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED, detail=str(exc)
        ) from exc
    except dockerfile_chat_service.GenerationFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
