from __future__ import annotations

import json
from typing import Any

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.dockerfiles import DisplayStatus, DockerfileSummary
from agflow.services import build_service, dockerfile_files_service

_log = structlog.get_logger(__name__)


class DockerfileNotFoundError(Exception):
    pass


class DuplicateDockerfileError(Exception):
    pass


def _parse_params(raw: Any) -> dict:
    if isinstance(raw, str):
        return json.loads(raw) if raw else {}
    return raw or {}


async def _image_exists(tag: str) -> bool:
    """Check whether a Docker image tag is present locally."""
    import aiodocker

    try:
        docker = aiodocker.Docker()
        try:
            await docker.images.inspect(tag)
            return True
        except aiodocker.exceptions.DockerError:
            return False
        finally:
            await docker.close()
    except Exception:
        return False


async def _compute_display_status(
    dockerfile_id: str,
) -> tuple[str, DisplayStatus, str | None]:
    """Return (current_hash, display_status, latest_build_id)."""
    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    current_hash = build_service.compute_hash(
        [{"path": f.path, "content": f.content} for f in files]
    )
    latest = await build_service.get_latest_build(dockerfile_id)
    if latest is None:
        return current_hash, "never_built", None

    latest_id = str(latest["id"])
    if latest["status"] == "failed":
        return current_hash, "failed", latest_id
    if latest["status"] in ("pending", "running"):
        return current_hash, "building", latest_id
    if latest["content_hash"] == current_hash and latest["status"] == "success":
        # Verify the image actually exists in Docker (may have been pruned)
        tag = build_service.image_tag_for(dockerfile_id, current_hash)
        if not await _image_exists(tag):
            return current_hash, "image_missing", latest_id
        return current_hash, "up_to_date", latest_id
    return current_hash, "outdated", latest_id


async def _row_to_summary(row: dict[str, Any]) -> DockerfileSummary:
    current_hash, display_status, latest_id = await _compute_display_status(row["id"])
    return DockerfileSummary(
        id=row["id"],
        display_name=row["display_name"],
        description=row["description"],
        parameters=_parse_params(row["parameters"]),
        current_hash=current_hash,
        display_status=display_status,
        latest_build_id=latest_id,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create(
    dockerfile_id: str,
    display_name: str,
    description: str = "",
    parameters: dict | None = None,
) -> DockerfileSummary:
    try:
        row = await fetch_one(
            """
            INSERT INTO dockerfiles (id, display_name, description, parameters)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING id, display_name, description, parameters,
                      created_at, updated_at
            """,
            dockerfile_id,
            display_name,
            description,
            json.dumps(parameters or {}),
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateDockerfileError(
            f"Dockerfile '{dockerfile_id}' already exists"
        ) from exc
    assert row is not None
    # Auto-seed the 2 standard files (Dockerfile + entrypoint.sh). They are
    # required by Module 1 spec and cannot be deleted afterward.
    from agflow.services import dockerfile_files_service
    await dockerfile_files_service.seed_standard_files(dockerfile_id)
    _log.info("dockerfiles.create", dockerfile_id=dockerfile_id)
    return await _row_to_summary(row)


async def list_all() -> list[DockerfileSummary]:
    rows = await fetch_all(
        """
        SELECT id, display_name, description, parameters, created_at, updated_at
        FROM dockerfiles
        ORDER BY id ASC
        """
    )
    return [await _row_to_summary(r) for r in rows]


async def get_by_id(dockerfile_id: str) -> DockerfileSummary:
    row = await fetch_one(
        """
        SELECT id, display_name, description, parameters, created_at, updated_at
        FROM dockerfiles
        WHERE id = $1
        """,
        dockerfile_id,
    )
    if row is None:
        raise DockerfileNotFoundError(f"Dockerfile '{dockerfile_id}' not found")
    return await _row_to_summary(row)


async def update(
    dockerfile_id: str,
    display_name: str | None = None,
    description: str | None = None,
    parameters: dict | None = None,
) -> DockerfileSummary:
    sets: list[str] = []
    args: list[Any] = []
    idx = 1
    if display_name is not None:
        sets.append(f"display_name = ${idx}")
        args.append(display_name)
        idx += 1
    if description is not None:
        sets.append(f"description = ${idx}")
        args.append(description)
        idx += 1
    if parameters is not None:
        sets.append(f"parameters = ${idx}::jsonb")
        args.append(json.dumps(parameters))
        idx += 1
    if not sets:
        return await get_by_id(dockerfile_id)
    sets.append("updated_at = NOW()")
    args.append(dockerfile_id)

    row = await fetch_one(
        f"""
        UPDATE dockerfiles SET {", ".join(sets)}
        WHERE id = ${idx}
        RETURNING id, display_name, description, parameters, created_at, updated_at
        """,
        *args,
    )
    if row is None:
        raise DockerfileNotFoundError(f"Dockerfile '{dockerfile_id}' not found")
    _log.info("dockerfiles.update", dockerfile_id=dockerfile_id)
    return await _row_to_summary(row)


async def delete(dockerfile_id: str) -> None:
    import os
    import shutil

    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM dockerfiles WHERE id = $1", dockerfile_id
        )
    if result == "DELETE 0":
        raise DockerfileNotFoundError(f"Dockerfile '{dockerfile_id}' not found")
    # Wipe the on-disk slug dir (sources, generated .tmp/, workspace, etc.).
    # Best-effort: log a warning if it fails, don't undo the DB delete.
    slug_dir = dockerfile_files_service._slug_dir(dockerfile_id)
    if os.path.isdir(slug_dir):
        try:
            shutil.rmtree(slug_dir)
        except OSError as exc:
            _log.warning(
                "dockerfiles.delete.fs_cleanup_failed",
                dockerfile_id=dockerfile_id,
                slug_dir=slug_dir,
                error=str(exc),
            )
    _log.info("dockerfiles.delete", dockerfile_id=dockerfile_id)
