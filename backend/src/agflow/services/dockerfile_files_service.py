from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from uuid import UUID

import structlog

from agflow.schemas.dockerfiles import FileSummary

_log = structlog.get_logger(__name__)

# Deterministic UUID5 namespace for file IDs — fixed forever.
_FILE_NS = uuid.UUID("a8f4c3b2-e7d6-4a1f-b5c9-0123456789ab")

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _file_id(dockerfile_id: str, path: str) -> uuid.UUID:
    """Deterministic UUID5 derived from (dockerfile_id, path)."""
    return uuid.uuid5(_FILE_NS, f"{dockerfile_id}:{path}")


def _data_dir() -> str:
    return os.environ.get("AGFLOW_DATA_DIR", "/app/data")


def _slug_dir(dockerfile_id: str) -> str:
    return os.path.join(_data_dir(), dockerfile_id)


def _file_summary(dockerfile_id: str, path: str, full_path: str) -> FileSummary:
    stat = os.stat(full_path)
    with open(full_path, encoding="utf-8") as fh:
        content = fh.read()
    return FileSummary(
        id=_file_id(dockerfile_id, path),
        dockerfile_id=dockerfile_id,
        path=path,
        content=content,
        created_at=datetime.fromtimestamp(stat.st_ctime, tz=UTC),
        updated_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
    )


# ---------------------------------------------------------------------------
# Public API  (async signatures preserved for caller compatibility)
# ---------------------------------------------------------------------------


async def seed_standard_files(dockerfile_id: str) -> list[FileSummary]:
    """Create the directory + standard files with their default content.

    Idempotent — skips files that already exist on disk.
    """
    slug_dir = _slug_dir(dockerfile_id)
    os.makedirs(slug_dir, exist_ok=True)
    created: list[FileSummary] = []
    for path, default_content in STANDARD_FILE_CONTENTS.items():
        full_path = os.path.join(slug_dir, path)
        if os.path.exists(full_path):
            continue
        with open(full_path, "w", encoding="utf-8") as fh:
            fh.write(default_content)
        created.append(_file_summary(dockerfile_id, path, full_path))
        _log.info("dockerfile_files.seed", dockerfile_id=dockerfile_id, path=path)
    return created


async def list_for_dockerfile(dockerfile_id: str) -> list[FileSummary]:
    slug_dir = _slug_dir(dockerfile_id)
    if not os.path.isdir(slug_dir):
        return []
    results: list[FileSummary] = []
    for filename in sorted(os.listdir(slug_dir)):
        full_path = os.path.join(slug_dir, filename)
        if os.path.isfile(full_path):
            results.append(_file_summary(dockerfile_id, filename, full_path))
    return results


async def create(
    dockerfile_id: str,
    path: str,
    content: str = "",
) -> FileSummary:
    slug_dir = _slug_dir(dockerfile_id)
    os.makedirs(slug_dir, exist_ok=True)
    full_path = os.path.join(slug_dir, path)
    if os.path.exists(full_path):
        raise DuplicateFileError(
            f"File '{path}' already exists in dockerfile '{dockerfile_id}'"
        )
    with open(full_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    _log.info("dockerfile_files.create", dockerfile_id=dockerfile_id, path=path)
    return _file_summary(dockerfile_id, path, full_path)


async def get_by_id(file_id: UUID) -> FileSummary:
    """Scan all dockerfile dirs to find the file with this deterministic UUID5."""
    base = _data_dir()
    if not os.path.isdir(base):
        raise FileNotFoundError(f"File {file_id} not found")
    for slug in sorted(os.listdir(base)):
        slug_path = os.path.join(base, slug)
        if not os.path.isdir(slug_path):
            continue
        for filename in os.listdir(slug_path):
            full_path = os.path.join(slug_path, filename)
            if not os.path.isfile(full_path):
                continue
            if _file_id(slug, filename) == file_id:
                return _file_summary(slug, filename, full_path)
    raise FileNotFoundError(f"File {file_id} not found")


async def update(file_id: UUID, content: str | None = None) -> FileSummary:
    if content is None:
        return await get_by_id(file_id)
    existing = await get_by_id(file_id)
    full_path = os.path.join(_slug_dir(existing.dockerfile_id), existing.path)
    with open(full_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    _log.info("dockerfile_files.update", file_id=str(file_id))
    return _file_summary(existing.dockerfile_id, existing.path, full_path)


async def delete(file_id: UUID) -> None:
    existing = await get_by_id(file_id)
    if existing.path in PROTECTED_FILES:
        raise ProtectedFileError(
            f"File '{existing.path}' is protected and cannot be deleted"
        )
    full_path = os.path.join(_slug_dir(existing.dockerfile_id), existing.path)
    os.unlink(full_path)
    _log.info("dockerfile_files.delete", file_id=str(file_id))


async def replace_all(
    dockerfile_id: str,
    files_map: dict[str, str],
) -> list[FileSummary]:
    """Wipe all existing files of a dockerfile and write the given set.

    Used by the zip import feature. Bypasses the PROTECTED_FILES check on
    purpose — protected files are still being REPLACED with fresh content
    coming from the import, not removed.
    """
    slug_dir = _slug_dir(dockerfile_id)
    # Remove existing files
    if os.path.isdir(slug_dir):
        for filename in os.listdir(slug_dir):
            full_path = os.path.join(slug_dir, filename)
            if os.path.isfile(full_path):
                os.unlink(full_path)
    else:
        os.makedirs(slug_dir, exist_ok=True)
    # Write new files
    for path, content in files_map.items():
        with open(os.path.join(slug_dir, path), "w", encoding="utf-8") as fh:
            fh.write(content)
    _log.info(
        "dockerfile_files.replace_all",
        dockerfile_id=dockerfile_id,
        file_count=len(files_map),
    )
    return await list_for_dockerfile(dockerfile_id)


# ---------------------------------------------------------------------------
# One-time migration: DB → filesystem
# ---------------------------------------------------------------------------


async def migrate_db_to_disk() -> None:
    """One-time migration: read all files from the legacy DB table and write
    them to disk. Idempotent — skips files that already exist on disk.
    """
    from agflow.db.pool import fetch_all  # imported lazily — may not be available

    try:
        rows = await fetch_all(
            "SELECT dockerfile_id, path, content FROM dockerfile_files"
        )
    except Exception as exc:
        _log.warning(
            "dockerfile_files.migrate_db_to_disk.skip",
            reason=str(exc),
        )
        return

    migrated = 0
    skipped = 0
    for row in rows:
        dockerfile_id: str = row["dockerfile_id"]
        path: str = row["path"]
        content: str = row["content"] or ""
        slug_dir = _slug_dir(dockerfile_id)
        os.makedirs(slug_dir, exist_ok=True)
        full_path = os.path.join(slug_dir, path)
        if os.path.exists(full_path):
            skipped += 1
            continue
        with open(full_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        migrated += 1

    _log.info(
        "dockerfile_files.migrate_db_to_disk.done",
        migrated=migrated,
        skipped=skipped,
    )
