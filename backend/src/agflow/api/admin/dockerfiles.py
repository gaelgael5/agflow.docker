from __future__ import annotations

import io
import json
import zipfile
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
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
    container_runner,
    dockerfile_chat_service,
    dockerfile_files_service,
    dockerfiles_service,
)


class ChatGenerateRequest(BaseModel):
    description: str = Field(min_length=10, max_length=4000)


class MountCheckEntry(BaseModel):
    source: str = ""
    target: str = ""
    readonly: bool = False


class MountCheckRequest(BaseModel):
    mounts: list[MountCheckEntry] = Field(default_factory=list)
    params: dict[str, str] = Field(default_factory=dict)


class MountCheckResult(BaseModel):
    source_original: str
    source_resolved: str
    auto_prefixed: bool
    exists: bool | None  # None when we can't check (absolute path)


class MountCheckResponse(BaseModel):
    results: list[MountCheckResult]

router = APIRouter(
    prefix="/api/admin/dockerfiles",
    tags=["admin-dockerfiles"],
    dependencies=[Depends(require_admin)],
)


@router.get(
    "",
    response_model=list[DockerfileSummary],
    summary="List all dockerfiles",
    description="Returns all registered agent dockerfiles as a list of DockerfileSummary objects, including their id, display name, description, and current content hash.",
)
async def list_dockerfiles() -> list[DockerfileSummary]:
    return await dockerfiles_service.list_all()


@router.post(
    "",
    response_model=DockerfileSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a dockerfile",
    description="Registers a new dockerfile entry with its display name, description, and parameter definitions. Returns 201 with the DockerfileSummary, or 409 if the id already exists.",
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


_REQUIRED_IMPORT_FILES = ("Dockerfile", "entrypoint.sh", "Dockerfile.json")
_MAX_IMPORT_ZIP_BYTES = 10 * 1024 * 1024  # 10 MB — dockerfile dirs are small


def _validate_dockerfile_json(raw: str) -> list[str]:
    """Return a list of validation errors for a Dockerfile.json payload.

    Expected shape:
        {
            "docker": { ... },
            "Params": { ... }
        }
    Empty list means the file is valid.
    """
    errors: list[str] = []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        errors.append(
            f"Dockerfile.json n'est pas du JSON valide : {exc.msg} "
            f"(ligne {exc.lineno}, colonne {exc.colno})"
        )
        return errors
    if not isinstance(parsed, dict):
        errors.append("Dockerfile.json doit avoir un objet à la racine")
        return errors
    if "docker" not in parsed:
        errors.append("Dockerfile.json : clé racine 'docker' manquante")
    elif not isinstance(parsed["docker"], dict):
        errors.append("Dockerfile.json : 'docker' doit être un objet")
    if "Params" not in parsed:
        errors.append("Dockerfile.json : clé racine 'Params' manquante")
    elif not isinstance(parsed["Params"], dict):
        errors.append("Dockerfile.json : 'Params' doit être un objet")
    return errors


@router.post(
    "/{dockerfile_id}/import",
    response_model=DockerfileDetail,
    summary="Import dockerfile files from a ZIP archive",
    description="Replace the entire directory of a dockerfile with the contents of a zip. Validates the zip before applying: is a valid zip archive, contains Dockerfile, entrypoint.sh and Dockerfile.json, all entries are flat files (no subdirectories), all entries decode as UTF-8 text, and Dockerfile.json parses as JSON with the expected shape. On any validation failure, returns 400 with a structured list of errors. On success, transactionally wipes all existing files and inserts the new set; returns the updated detail.",
)
async def import_dockerfile(
    dockerfile_id: str, file: UploadFile = File(...)
) -> DockerfileDetail:
    """Replace the entire directory of a dockerfile with the contents of a zip.

    Validates the zip before applying:
      * is a valid zip archive
      * contains Dockerfile, entrypoint.sh and Dockerfile.json
      * all entries are flat files (no subdirectories)
      * all entries decode as UTF-8 text
      * Dockerfile.json parses as JSON with the expected shape

    On any validation failure, returns 400 with a structured list of errors.
    On success, transactionally wipes all existing files and inserts the new
    set; returns the updated detail.
    """
    try:
        await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    content = await file.read()
    if len(content) > _MAX_IMPORT_ZIP_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "errors": [
                    f"Le zip dépasse la taille maximale de "
                    f"{_MAX_IMPORT_ZIP_BYTES // (1024 * 1024)} Mo."
                ]
            },
        )

    errors: list[str] = []

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "errors": [
                    "Le fichier fourni n'est pas une archive zip valide."
                ]
            },
        ) from None

    files_map: dict[str, str] = {}
    for info in zf.infolist():
        name = info.filename
        if info.is_dir() or name.endswith("/"):
            continue
        if ".." in name.split("/") or name.startswith("/"):
            errors.append(f"'{name}' : chemin invalide.")
            continue
        try:
            files_map[name] = zf.read(info).decode("utf-8")
        except UnicodeDecodeError:
            errors.append(
                f"'{name}' : contenu non décodable en UTF-8 "
                f"(seuls les fichiers texte sont supportés)."
            )

    # Required files must all be present.
    missing = [p for p in _REQUIRED_IMPORT_FILES if p not in files_map]
    if missing:
        errors.append(
            "Fichiers requis manquants dans le zip : "
            + ", ".join(missing)
            + "."
        )

    # Dockerfile.json structural validation.
    if "Dockerfile.json" in files_map:
        errors.extend(_validate_dockerfile_json(files_map["Dockerfile.json"]))

    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"errors": errors},
        )

    # Apply — transactional replace.
    await dockerfile_files_service.replace_all(dockerfile_id, files_map)

    # Return the fresh detail.
    dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    files = await dockerfile_files_service.list_for_dockerfile(
        dockerfile_id, include_dirs=True
    )
    return DockerfileDetail(dockerfile=dockerfile, files=files)


@router.get(
    "/{dockerfile_id}/export",
    summary="Export dockerfile files as a ZIP archive",
    description="Return a zip archive containing every file of the dockerfile directory. The archive is built in-memory and streamed back with a Content-Disposition header so the browser triggers a download. Returns 404 if the dockerfile does not exist.",
)
async def export_dockerfile(dockerfile_id: str) -> StreamingResponse:
    """Return a zip archive containing every file of the dockerfile directory.

    The archive is built in-memory (dockerfile directories are small — a few
    files of a few KB each) and streamed back with a Content-Disposition
    header so the browser triggers a download.
    """
    try:
        await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

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


@router.get(
    "/{dockerfile_id}",
    response_model=DockerfileDetail,
    summary="Get dockerfile detail with files",
    description="Returns the full DockerfileDetail for the given dockerfile, including its metadata and the list of all associated files and directories. Returns 404 if not found.",
)
async def get_dockerfile(dockerfile_id: str) -> DockerfileDetail:
    try:
        dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    files = await dockerfile_files_service.list_for_dockerfile(
        dockerfile_id, include_dirs=True
    )
    return DockerfileDetail(dockerfile=dockerfile, files=files)


@router.put(
    "/{dockerfile_id}",
    response_model=DockerfileSummary,
    summary="Update a dockerfile",
    description="Partially updates a dockerfile's metadata (display name, description, parameters). Returns the updated DockerfileSummary, or 404 if not found.",
)
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


@router.delete(
    "/{dockerfile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dockerfile",
    description="Permanently deletes the dockerfile and all its associated files. Returns 204 on success, or 404 if the dockerfile does not exist.",
)
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
    summary="Create a file inside a dockerfile",
    description="Adds a new text file at the given path inside the dockerfile's data directory. Returns 201 with the FileSummary, or 409 if a file at that path already exists.",
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


@router.put(
    "/{dockerfile_id}/files/{file_id}",
    response_model=FileSummary,
    summary="Update a file inside a dockerfile",
    description="Replaces the text content of the specified file. Returns the updated FileSummary, or 404 if the file does not exist.",
)
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
    summary="Delete a file inside a dockerfile",
    description="Permanently deletes the specified file. Returns 204 on success, 404 if not found, or 403 if the file is protected and cannot be deleted.",
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


@router.delete(
    "/{dockerfile_id}/dirs",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a directory inside a dockerfile",
    description="Recursively deletes a directory and all its contents inside the dockerfile's data directory. Returns 204 on success, or 404 if the directory does not exist.",
)
async def delete_dir(dockerfile_id: str, path: str) -> None:
    """Recursively delete a directory inside the dockerfile's data dir."""
    try:
        await dockerfile_files_service.delete_dir(dockerfile_id, path)
    except dockerfile_files_service.FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/{dockerfile_id}/build",
    response_model=BuildSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a Docker image build",
    description="Enqueues an asynchronous Docker image build for the given dockerfile. Returns 202 with an initial BuildSummary (status=pending); poll GET /{dockerfile_id}/builds/{build_id} to track progress. Returns 404 if the dockerfile does not exist.",
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


@router.get(
    "/{dockerfile_id}/builds",
    response_model=list[BuildSummary],
    summary="List builds for a dockerfile",
    description="Returns all build records for the specified dockerfile as a list of BuildSummary objects, ordered by creation date descending.",
)
async def list_builds(dockerfile_id: str) -> list[BuildSummary]:
    rows = await build_service.list_builds(dockerfile_id)
    return [BuildSummary(**r) for r in rows]


@router.get(
    "/{dockerfile_id}/builds/{build_id}",
    response_model=BuildSummary,
    summary="Get a specific build record",
    description="Returns the BuildSummary for the specified build, including its current status, logs, and image tag. Returns 404 if the build does not exist or does not belong to the given dockerfile.",
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


@router.post(
    "/{dockerfile_id}/check-mounts",
    response_model=MountCheckResponse,
    summary="Check mount source paths for a dockerfile",
    description="Resolve each mount source and report whether it exists on disk. Used by the Paramètres dialog to surface a red/green indicator next to each mount entry. Takes the raw (possibly unsaved) mounts and params so the UI can live-preview even before the user clicks Save.",
)
async def check_mounts(
    dockerfile_id: str, payload: MountCheckRequest
) -> MountCheckResponse:
    """Resolve each mount source and report whether it exists on disk.

    Used by the Paramètres dialog to surface a red/green indicator next to
    each mount entry. Takes the raw (possibly unsaved) mounts + params so
    the UI can live-preview even before the user clicks Save.
    """
    try:
        await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    vars_map: dict[str, str] = {
        **payload.params,
        "slug": dockerfile_id,
    }
    results: list[MountCheckResult] = []
    for m in payload.mounts:
        source = (m.source or "").strip()
        if not source:
            continue
        host_path, container_path, auto = container_runner.resolve_mount_source(
            source, dockerfile_id, vars_map
        )
        exists = container_runner.check_mount_source(container_path)
        results.append(
            MountCheckResult(
                source_original=source,
                source_resolved=host_path,
                auto_prefixed=auto,
                exists=exists,
            )
        )
    return MountCheckResponse(results=results)


@router.post(
    "/chat-generate",
    summary="Generate a Dockerfile from a natural language description",
    description="Calls Anthropic Claude to generate a Dockerfile and entrypoint.sh from a plain-text description. Stateless — the client shows the result, lets the user approve, then creates the dockerfile via the regular POST endpoint. Returns 412 if the ANTHROPIC_API_KEY secret is missing, or 502 if generation fails.",
)
async def chat_generate_dockerfile(
    payload: ChatGenerateRequest,
) -> dockerfile_chat_service.GeneratedDockerfile:
    """Generate Dockerfile + entrypoint.sh from a natural
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
