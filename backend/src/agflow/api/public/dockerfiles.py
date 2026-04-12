from __future__ import annotations

import io
import zipfile
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from agflow.api.admin.dockerfiles import (
    _MAX_IMPORT_ZIP_BYTES,
    _REQUIRED_IMPORT_FILES,
    _validate_dockerfile_json,
)
from agflow.api.public.errors import api_error
from agflow.auth.api_key import require_api_key
from agflow.schemas.dockerfiles import (
    BuildSummary,
    DockerfileCreate,
    DockerfileDetail,
    DockerfileSummary,
    DockerfileUpdate,
)
from agflow.services import (
    build_service,
    dockerfile_files_service,
    dockerfiles_service,
)

router = APIRouter(
    prefix="/api/v1/dockerfiles",
    tags=["public-dockerfiles"],
)


@router.get("", response_model=list[DockerfileSummary])
async def list_dockerfiles(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _key: dict = require_api_key("dockerfiles:read"),
) -> list[DockerfileSummary]:
    rows = await dockerfiles_service.list_all()
    return rows[offset : offset + limit]


@router.get("/{dockerfile_id}", response_model=DockerfileDetail)
async def get_dockerfile(
    dockerfile_id: str,
    _key: dict = require_api_key("dockerfiles:read"),
) -> DockerfileDetail:
    try:
        dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise api_error(404, "not_found", str(exc)) from exc
    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    return DockerfileDetail(dockerfile=dockerfile, files=files)


@router.post(
    "", response_model=DockerfileSummary, status_code=status.HTTP_201_CREATED
)
async def create_dockerfile(
    payload: DockerfileCreate,
    _key: dict = require_api_key("dockerfiles:write"),
) -> DockerfileSummary:
    try:
        return await dockerfiles_service.create(
            dockerfile_id=payload.id,
            display_name=payload.display_name,
            description=payload.description,
            parameters=payload.parameters,
        )
    except dockerfiles_service.DuplicateDockerfileError as exc:
        raise api_error(409, "conflict", str(exc)) from exc


@router.put("/{dockerfile_id}", response_model=DockerfileSummary)
async def update_dockerfile(
    dockerfile_id: str,
    payload: DockerfileUpdate,
    _key: dict = require_api_key("dockerfiles:write"),
) -> DockerfileSummary:
    try:
        return await dockerfiles_service.update(
            dockerfile_id,
            **payload.model_dump(exclude_unset=True),
        )
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise api_error(404, "not_found", str(exc)) from exc


@router.delete("/{dockerfile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dockerfile(
    dockerfile_id: str,
    _key: dict = require_api_key("dockerfiles:delete"),
) -> None:
    try:
        await dockerfiles_service.delete(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise api_error(404, "not_found", str(exc)) from exc


@router.post(
    "/{dockerfile_id}/build",
    response_model=BuildSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_build(
    dockerfile_id: str,
    background: BackgroundTasks,
    _key: dict = require_api_key("dockerfiles:build"),
) -> BuildSummary:
    try:
        dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise api_error(404, "not_found", str(exc)) from exc

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
async def list_builds(
    dockerfile_id: str,
    _key: dict = require_api_key("dockerfiles:read"),
) -> list[BuildSummary]:
    rows = await build_service.list_builds(dockerfile_id)
    return [BuildSummary(**r) for r in rows]


@router.get("/{dockerfile_id}/export")
async def export_dockerfile(
    dockerfile_id: str,
    _key: dict = require_api_key("dockerfiles:read"),
) -> StreamingResponse:
    """Return a zip archive containing every file of the dockerfile directory."""
    try:
        await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise api_error(404, "not_found", str(exc)) from exc

    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f.path, f.content)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{dockerfile_id}.zip"',
        },
    )


@router.post("/{dockerfile_id}/import", response_model=DockerfileDetail)
async def import_dockerfile(
    dockerfile_id: str,
    file: UploadFile = File(...),
    _key: dict = require_api_key("dockerfiles:write"),
) -> DockerfileDetail:
    """Replace the entire directory of a dockerfile with the contents of a zip.

    Validates the zip before applying:
      * is a valid zip archive
      * contains Dockerfile, entrypoint.sh and Dockerfile.json
      * all entries are flat files (no subdirectories)
      * all entries decode as UTF-8 text
      * Dockerfile.json parses as JSON with the expected shape

    On any validation failure, returns 400 with a structured error.
    On success, transactionally wipes all existing files and inserts the new
    set; returns the updated detail.
    """
    try:
        await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise api_error(404, "not_found", str(exc)) from exc

    content = await file.read()
    if len(content) > _MAX_IMPORT_ZIP_BYTES:
        raise api_error(
            413,
            "payload_too_large",
            f"Le zip dépasse la taille maximale de "
            f"{_MAX_IMPORT_ZIP_BYTES // (1024 * 1024)} Mo.",
        )

    errors: list[str] = []

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise api_error(
            400, "invalid_zip", "Le fichier fourni n'est pas une archive zip valide."
        ) from None

    files_map: dict[str, str] = {}
    for info in zf.infolist():
        name = info.filename
        if info.is_dir() or name.endswith("/"):
            continue
        if "/" in name or "\\" in name:
            errors.append(
                f"'{name}' : les sous-répertoires ne sont pas autorisés "
                f"(seuls les fichiers à la racine du zip sont acceptés)."
            )
            continue
        try:
            files_map[name] = zf.read(info).decode("utf-8")
        except UnicodeDecodeError:
            errors.append(
                f"'{name}' : contenu non décodable en UTF-8 "
                f"(seuls les fichiers texte sont supportés)."
            )

    missing = [p for p in _REQUIRED_IMPORT_FILES if p not in files_map]
    if missing:
        errors.append(
            "Fichiers requis manquants dans le zip : "
            + ", ".join(missing)
            + "."
        )

    if "Dockerfile.json" in files_map:
        errors.extend(_validate_dockerfile_json(files_map["Dockerfile.json"]))

    if errors:
        raise api_error(400, "validation_error", "; ".join(errors))

    await dockerfile_files_service.replace_all(dockerfile_id, files_map)

    dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    return DockerfileDetail(dockerfile=dockerfile, files=files)
