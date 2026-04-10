from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.dockerfiles import FileSummary

_log = structlog.get_logger(__name__)

_FILE_COLS = "id, dockerfile_id, path, content, created_at, updated_at"


class FileNotFoundError(Exception):
    pass


class DuplicateFileError(Exception):
    pass


def _row(row: dict) -> FileSummary:
    return FileSummary(**row)


async def create(
    dockerfile_id: str,
    path: str,
    content: str = "",
) -> FileSummary:
    try:
        row = await fetch_one(
            f"""
            INSERT INTO dockerfile_files (dockerfile_id, path, content)
            VALUES ($1, $2, $3)
            RETURNING {_FILE_COLS}
            """,
            dockerfile_id,
            path,
            content,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateFileError(
            f"File '{path}' already exists in dockerfile '{dockerfile_id}'"
        ) from exc
    assert row is not None
    _log.info("dockerfile_files.create", dockerfile_id=dockerfile_id, path=path)
    return _row(row)


async def get_by_id(file_id: UUID) -> FileSummary:
    row = await fetch_one(
        f"SELECT {_FILE_COLS} FROM dockerfile_files WHERE id = $1", file_id
    )
    if row is None:
        raise FileNotFoundError(f"File {file_id} not found")
    return _row(row)


async def list_for_dockerfile(dockerfile_id: str) -> list[FileSummary]:
    rows = await fetch_all(
        f"""
        SELECT {_FILE_COLS} FROM dockerfile_files
        WHERE dockerfile_id = $1
        ORDER BY path ASC
        """,
        dockerfile_id,
    )
    return [_row(r) for r in rows]


async def update(file_id: UUID, content: str | None = None) -> FileSummary:
    if content is None:
        return await get_by_id(file_id)
    row = await fetch_one(
        f"""
        UPDATE dockerfile_files
        SET content = $2, updated_at = NOW()
        WHERE id = $1
        RETURNING {_FILE_COLS}
        """,
        file_id,
        content,
    )
    if row is None:
        raise FileNotFoundError(f"File {file_id} not found")
    _log.info("dockerfile_files.update", file_id=str(file_id))
    return _row(row)


async def delete(file_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM dockerfile_files WHERE id = $1", file_id
        )
    if result == "DELETE 0":
        raise FileNotFoundError(f"File {file_id} not found")
    _log.info("dockerfile_files.delete", file_id=str(file_id))
