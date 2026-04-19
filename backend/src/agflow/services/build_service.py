from __future__ import annotations

import hashlib
import io
import tarfile
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import aiodocker
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.services import dockerfile_files_service

_log = structlog.get_logger(__name__)


@dataclass
class FileDTO:
    path: str
    content: str


def compute_hash(files: Iterable[dict | FileDTO]) -> str:
    """SHA256 of Dockerfile + all *.sh files sorted alphabetically.

    Returns the first 12 hex chars, suitable for use as an image tag.
    """
    normalized: list[FileDTO] = []
    for f in files:
        if isinstance(f, FileDTO):
            normalized.append(f)
        else:
            normalized.append(FileDTO(path=f["path"], content=f["content"]))

    relevant = sorted(
        (
            f for f in normalized
            if (f.path == "Dockerfile" or f.path.endswith(".sh"))
            and not f.path.startswith(".tmp/")
        ),
        key=lambda f: f.path,
    )
    h = hashlib.sha256()
    for f in relevant:
        h.update(f.path.encode())
        h.update(b"\n")
        h.update(f.content.encode())
        h.update(b"\n---\n")
    return h.hexdigest()[:12]


def image_tag_for(dockerfile_id: str, content_hash: str) -> str:
    return f"agflow-{dockerfile_id}:{content_hash}"


def _build_tar_context(files: list[FileDTO]) -> bytes:
    """Create an in-memory tar archive containing all files at the tar root."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for f in files:
            data = f.content.encode()
            info = tarfile.TarInfo(name=f.path)
            info.size = len(data)
            info.mode = 0o755 if f.path.endswith(".sh") else 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


async def _append_log(build_id: UUID, chunk: str) -> None:
    await execute(
        "UPDATE dockerfile_builds SET logs = logs || $2 WHERE id = $1",
        build_id,
        chunk,
    )


async def _set_status(
    build_id: UUID, status: str, finished: bool = False
) -> None:
    if finished:
        await execute(
            "UPDATE dockerfile_builds SET status = $2, finished_at = NOW() WHERE id = $1",
            build_id,
            status,
        )
    else:
        await execute(
            "UPDATE dockerfile_builds SET status = $2 WHERE id = $1",
            build_id,
            status,
        )


async def run_build(build_id: UUID, dockerfile_id: str, tag: str) -> None:
    """Run a docker build for a previously-recorded build row.

    Streams logs into the `logs` column. Flips `status` at the end.
    """
    files_list = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    files = [FileDTO(path=f.path, content=f.content) for f in files_list]

    has_dockerfile = any(f.path == "Dockerfile" for f in files)
    if not has_dockerfile:
        await _append_log(
            build_id, "ERROR: no file named 'Dockerfile' in this dockerfile\n"
        )
        await _set_status(build_id, "failed", finished=True)
        return

    context = _build_tar_context(files)

    await _set_status(build_id, "running")
    _log.info(
        "build.start", dockerfile_id=dockerfile_id, tag=tag, build_id=str(build_id)
    )

    try:
        docker = aiodocker.Docker()
        try:
            async for chunk in docker.images.build(
                fileobj=io.BytesIO(context),
                encoding="identity",
                tag=tag,
                stream=True,
            ):
                line = _format_chunk(chunk)
                if line:
                    await _append_log(build_id, line + "\n")
        finally:
            await docker.close()
    except Exception as exc:
        _log.exception("build.error", build_id=str(build_id))
        await _append_log(build_id, f"\nBUILD ERROR: {exc}\n")
        await _set_status(build_id, "failed", finished=True)
        return

    await _set_status(build_id, "success", finished=True)
    _log.info("build.done", build_id=str(build_id))

    # Cleanup old builds (images + DB rows)
    await _cleanup_old_builds(dockerfile_id, keep_build_id=build_id, keep_tag=tag)


def _format_chunk(chunk: Any) -> str:
    if isinstance(chunk, dict):
        if "stream" in chunk:
            return chunk["stream"].rstrip("\n")
        if "error" in chunk:
            return f"ERROR: {chunk['error']}"
        if "status" in chunk:
            return chunk["status"]
    return str(chunk).rstrip("\n")


async def _cleanup_old_builds(
    dockerfile_id: str, keep_build_id: UUID, keep_tag: str
) -> None:
    """Remove old Docker images and DB build rows for this dockerfile."""
    old_builds = await fetch_all(
        "SELECT id, image_tag FROM dockerfile_builds "
        "WHERE dockerfile_id = $1 AND id != $2",
        dockerfile_id, keep_build_id,
    )
    if not old_builds:
        return

    # Remove old Docker images
    try:
        docker = aiodocker.Docker()
        try:
            for build in old_builds:
                old_tag = build["image_tag"]
                if old_tag == keep_tag:
                    continue
                try:
                    await docker.images.delete(old_tag, force=True)
                    _log.info("build.cleanup.image_removed", tag=old_tag)
                except aiodocker.exceptions.DockerError:
                    pass  # Image already gone
        finally:
            await docker.close()
    except Exception:
        _log.warning("build.cleanup.docker_error", dockerfile_id=dockerfile_id)

    # Remove old DB rows
    await execute(
        "DELETE FROM dockerfile_builds WHERE dockerfile_id = $1 AND id != $2",
        dockerfile_id, keep_build_id,
    )
    _log.info(
        "build.cleanup.rows_deleted",
        dockerfile_id=dockerfile_id,
        count=len(old_builds),
    )


async def create_build_row(
    dockerfile_id: str, content_hash: str, tag: str
) -> UUID:
    row = await fetch_one(
        """
        INSERT INTO dockerfile_builds (dockerfile_id, content_hash, image_tag)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        dockerfile_id,
        content_hash,
        tag,
    )
    assert row is not None
    return row["id"]


async def get_latest_build(dockerfile_id: str) -> dict | None:
    return await fetch_one(
        """
        SELECT id, content_hash, status FROM dockerfile_builds
        WHERE dockerfile_id = $1
        ORDER BY started_at DESC
        LIMIT 1
        """,
        dockerfile_id,
    )


async def list_builds(dockerfile_id: str) -> list[dict]:
    return await fetch_all(
        """
        SELECT id, dockerfile_id, content_hash, image_tag, status, logs,
               started_at, finished_at
        FROM dockerfile_builds
        WHERE dockerfile_id = $1
        ORDER BY started_at DESC
        """,
        dockerfile_id,
    )


async def get_build(build_id: UUID) -> dict | None:
    return await fetch_one(
        """
        SELECT id, dockerfile_id, content_hash, image_tag, status, logs,
               started_at, finished_at
        FROM dockerfile_builds
        WHERE id = $1
        """,
        build_id,
    )
