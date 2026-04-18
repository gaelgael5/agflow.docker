from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any
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
      { "source": "{WORKSPACE_PATH}", "target": "/app/workspace", "readonly": false }
    ]
  },
  "Params": {
    "API_KEY_NAME":   "ANTHROPIC_API_KEY",
    "WORKSPACE_PATH": "${WORKSPACE_PATH:-./workspace}"
  }
}
"""

_DESCRIPTION_MD_DEFAULT = """# Description

Décris ici le rôle et le comportement attendu de cet agent.
"""

_HELP_FR_DEFAULT = """# Aide — {slug}

## Prérequis

- Abonnement au fournisseur LLM correspondant
- Clé API configurée dans les secrets plateforme

## Variables d'environnement

| Variable | Description | Obligatoire |
|----------|-------------|-------------|
| `API_KEY` | Clé API du fournisseur LLM | Oui |

## Paramètres

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `WORKSPACE_PATH` | `./workspace` | Chemin du workspace monté dans le container |

## Utilisation

1. Compiler l'image (bouton Build)
2. Créer un agent qui utilise ce Dockerfile
3. Configurer les secrets requis
4. Lancer depuis le chat ou l'API

## Notes

- Le container utilise `entrypoint.sh` comme point d'entrée
- Le workspace est monté dans `/app/workspace`
"""

_HELP_EN_DEFAULT = """# Help — {slug}

## Prerequisites

- Subscription to the corresponding LLM provider
- API key configured in platform secrets

## Environment variables

| Variable | Description | Required |
|----------|-------------|----------|
| `API_KEY` | LLM provider API key | Yes |

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `WORKSPACE_PATH` | `./workspace` | Workspace path mounted in the container |

## Usage

1. Build the image (Build button)
2. Create an agent using this Dockerfile
3. Configure required secrets
4. Launch from chat or API

## Notes

- The container uses `entrypoint.sh` as entry point
- Workspace is mounted at `/app/workspace`
"""

_ENTRYPOINT_SH_DEFAULT = """#!/usr/bin/env bash
set -euo pipefail

# Keep the container alive so you can `docker exec -ti` into it for
# exploration. Replace with the real agent command when ready.
exec sleep infinity
"""

STANDARD_FILE_CONTENTS: dict[str, str] = {
    "Dockerfile": "",
    "entrypoint.sh": _ENTRYPOINT_SH_DEFAULT,
    "Dockerfile.json": _DOCKERFILE_JSON_DEFAULT,
    "description.md": _DESCRIPTION_MD_DEFAULT,
    "help.fr.md": _HELP_FR_DEFAULT,
    "help.en.md": _HELP_EN_DEFAULT,
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
    "description.md",
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
        type="file",
        size=stat.st_size,
        created_at=datetime.fromtimestamp(stat.st_ctime, tz=UTC),
        updated_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
    )


def _dir_summary(dockerfile_id: str, path: str, full_path: str) -> FileSummary:
    stat = os.stat(full_path)
    return FileSummary(
        id=_file_id(dockerfile_id, path),
        dockerfile_id=dockerfile_id,
        path=path,
        content="",
        type="dir",
        size=0,
        created_at=datetime.fromtimestamp(stat.st_ctime, tz=UTC),
        updated_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
    )


def read_target(dockerfile_id: str) -> dict | None:
    """Read the Target block from Dockerfile.json, or None if absent."""
    json_path = os.path.join(_slug_dir(dockerfile_id), "Dockerfile.json")
    if not os.path.isfile(json_path):
        return None
    with open(json_path, encoding="utf-8") as f:
        data = json.loads(f.read())
    return data.get("Target")


DEFAULT_GENERATION_CONFIG: dict[str, Any] = {
    "base_dir": "workspace",
    "prompt_ref_prefix": "@workspace",
    "paths": {
        "prompt": "prompt.md",
        "roles": "roles.md",
        "env": ".env",
        "run": "run.sh",
        "mcp_config": "config.toml",
        "mcp_json": "mcp.json",
        "docs": "docs",
        "missions": "docs/missions",
        "contracts": "docs/ctr",
        "skills": "docs/skills",
    },
}


def read_generation_config(dockerfile_id: str) -> dict[str, Any]:
    """Read the Generation block from Dockerfile.json, with defaults.

    If base_dir / prompt_ref_prefix are not explicitly set in the Generation
    block, they are derived from docker.Runtime.WorkingDir:
        -w /app/workspace  → base_dir="workspace", ref_prefix="@workspace"
        -w /.vibes          → base_dir=".vibes",     ref_prefix="@"
    """
    json_path = os.path.join(_slug_dir(dockerfile_id), "Dockerfile.json")
    if not os.path.isfile(json_path):
        return {**DEFAULT_GENERATION_CONFIG, "paths": {**DEFAULT_GENERATION_CONFIG["paths"]}}

    with open(json_path, encoding="utf-8") as f:
        data = json.loads(f.read())

    gen = data.get("Generation") or {}

    result = {**DEFAULT_GENERATION_CONFIG, **gen}
    result["paths"] = {**DEFAULT_GENERATION_CONFIG["paths"], **gen.get("paths", {})}

    # Auto-derive base_dir from WorkingDir if not explicitly set
    # -w /vibes → base_dir="vibes", ref_prefix="@"
    # -w /app/workspace → base_dir="workspace", ref_prefix="@workspace" (default)
    if "base_dir" not in gen:
        workdir = (data.get("docker", {}).get("Runtime", {}).get("WorkingDir", "") or "").strip().rstrip("/")
        if workdir:
            # /vibes → vibes, /app/workspace → workspace
            base = workdir.split("/")[-1]
            if base and base != DEFAULT_GENERATION_CONFIG["base_dir"]:
                result["base_dir"] = base
                result["prompt_ref_prefix"] = "@"

    return result


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
        content = default_content.replace("{slug}", dockerfile_id)
        with open(full_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        created.append(_file_summary(dockerfile_id, path, full_path))
        _log.info("dockerfile_files.seed", dockerfile_id=dockerfile_id, path=path)
    return created


async def list_for_dockerfile(
    dockerfile_id: str, *, include_dirs: bool = False
) -> list[FileSummary]:
    from agflow.services.fs_walker import walk_tree

    slug_dir = _slug_dir(dockerfile_id)
    results: list[FileSummary] = []
    for entry in walk_tree(slug_dir):
        if entry.type == "dir":
            if include_dirs:
                results.append(
                    _dir_summary(dockerfile_id, entry.path, entry.full_path)
                )
            continue
        results.append(_file_summary(dockerfile_id, entry.path, entry.full_path))
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
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
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
        for dirpath, dirnames, filenames in os.walk(slug_path):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") or d == ".tmp"]
            for filename in filenames:
                full_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(full_path, slug_path).replace("\\", "/")
                if _file_id(slug, rel_path) == file_id:
                    return _file_summary(slug, rel_path, full_path)
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
    slug_dir = _slug_dir(existing.dockerfile_id)
    full_path = os.path.join(slug_dir, existing.path)
    os.unlink(full_path)
    parent = os.path.dirname(full_path)
    while parent != slug_dir and os.path.isdir(parent) and not os.listdir(parent):
        os.rmdir(parent)
        parent = os.path.dirname(parent)
    _log.info("dockerfile_files.delete", file_id=str(file_id))


async def delete_dir(dockerfile_id: str, rel_path: str) -> None:
    """Recursively delete a directory inside the dockerfile's data dir.

    Used by the file explorer to drop dirs that have no registered files (e.g.
    empty mount targets like ``config/``). Refuses any path that escapes the
    dockerfile's slug dir.
    """
    import shutil

    slug_dir = os.path.realpath(_slug_dir(dockerfile_id))
    norm_rel = rel_path.strip().strip("/").replace("\\", "/")
    if not norm_rel:
        raise FileNotFoundError("Empty directory path")
    target = os.path.realpath(os.path.join(slug_dir, norm_rel))
    if not target.startswith(slug_dir + os.sep):
        raise FileNotFoundError(f"Path '{rel_path}' is outside the dockerfile dir")
    if not os.path.isdir(target):
        raise FileNotFoundError(f"Directory '{rel_path}' not found")
    shutil.rmtree(target)
    _log.info("dockerfile_files.delete_dir", dockerfile_id=dockerfile_id, path=norm_rel)


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
    if os.path.isdir(slug_dir):
        import shutil

        shutil.rmtree(slug_dir)
    os.makedirs(slug_dir, exist_ok=True)
    for path, content in files_map.items():
        full_path = os.path.join(slug_dir, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as fh:
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
