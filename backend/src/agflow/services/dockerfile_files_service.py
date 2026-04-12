from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.dockerfiles import FileSummary

_log = structlog.get_logger(__name__)

_FILE_COLS = "id, dockerfile_id, path, content, created_at, updated_at"

# Standard files auto-seeded on dockerfile creation. They cannot be deleted,
# only edited. Mirrors the Module 1 spec requirement that every dockerfile
# must provide a Dockerfile, an entrypoint.sh and a Dockerfile.json (default
# parameters with agflow templating {KEY} + shell templating ${VAR}).
_DOCKERFILE_JSON_DEFAULT = """{
  "docker": {
    "Container": {
      "Name": "agent-{slug}-{id}",
      "Image": "agflow-{slug}:{hash}"
    },
    "Network": {
      "Mode": "bridge"
    },
    "Runtime": {
      "Init": true,
      "StopSignal": "SIGTERM",
      "StopTimeout": 30,
      "WorkingDir": "/app"
    },
    "Resources": {
      "Memory": "2g",
      "Cpus": "1.5"
    },
    "Environments": {
      "ANTHROPIC_API_KEY": "{API_KEY_NAME}"
    },
    "Mounts": [
      { "source": "{WORKSPACE_PATH}", "target": "/app/workspace", "readonly": false },
      { "source": "./config",         "target": "/app/config",    "readonly": true  },
      { "source": "./skills",         "target": "/app/skills",    "readonly": true  },
      { "source": "./output",         "target": "/app/output",    "readonly": false }
    ]
  },
  "Params": {
    "API_KEY_NAME":   "ANTHROPIC_API_KEY",
    "WORKSPACE_PATH": "${WORKSPACE_PATH:-./workspace}"
  }
}
"""

STANDARD_FILE_CONTENTS: dict[str, str] = {
    "Dockerfile": "",
    "entrypoint.sh": "",
    "Dockerfile.json": _DOCKERFILE_JSON_DEFAULT,
}

# All files auto-seeded on dockerfile creation.
STANDARD_FILES: tuple[str, ...] = tuple(STANDARD_FILE_CONTENTS.keys())

# Subset that cannot be deleted. Dockerfile.json is hidden from the UI but
# still protected so the parameters file cannot be wiped out via a stray
# API call.
PROTECTED_FILES: tuple[str, ...] = (
    "Dockerfile",
    "entrypoint.sh",
    "Dockerfile.json",
)


class FileNotFoundError(Exception):
    pass


class DuplicateFileError(Exception):
    pass


class ProtectedFileError(Exception):
    """Raised when attempting to delete a standard (non-deletable) file."""


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
    existing = await get_by_id(file_id)
    if existing.path in PROTECTED_FILES:
        raise ProtectedFileError(
            f"File '{existing.path}' is protected and cannot be deleted"
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM dockerfile_files WHERE id = $1", file_id
        )
    if result == "DELETE 0":
        raise FileNotFoundError(f"File {file_id} not found")
    _log.info("dockerfile_files.delete", file_id=str(file_id))


async def replace_all(
    dockerfile_id: str,
    files_map: dict[str, str],
) -> list[FileSummary]:
    """Transactionally wipe all existing files of a dockerfile and insert the
    given set in a single DB transaction.

    Used by the zip import feature. Bypasses the PROTECTED_FILES check on
    purpose — protected files are still being REPLACED with fresh content
    coming from the import, not removed.
    """
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "DELETE FROM dockerfile_files WHERE dockerfile_id = $1",
            dockerfile_id,
        )
        for path, content in files_map.items():
            await conn.execute(
                """
                INSERT INTO dockerfile_files (dockerfile_id, path, content)
                VALUES ($1, $2, $3)
                """,
                dockerfile_id,
                path,
                content,
            )
    _log.info(
        "dockerfile_files.replace_all",
        dockerfile_id=dockerfile_id,
        file_count=len(files_map),
    )
    return await list_for_dockerfile(dockerfile_id)


async def seed_standard_files(dockerfile_id: str) -> list[FileSummary]:
    """Create the standard files (Dockerfile, entrypoint.sh, Dockerfile.json)
    with their default content. Idempotent — skips files that already exist.
    """
    created: list[FileSummary] = []
    for path, default_content in STANDARD_FILE_CONTENTS.items():
        try:
            f = await create(dockerfile_id, path=path, content=default_content)
            created.append(f)
        except DuplicateFileError:
            continue
    return created
