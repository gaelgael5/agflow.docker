from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import get_pool
from agflow.schemas.dockerfiles import FileSummary
from agflow.storage import StorageSDK

_log = structlog.get_logger(__name__)

_DOCKERFILES_ROOT = "Dockerfiles"

# Standard files auto-seeded on dockerfile creation.
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

STANDARD_FILES: tuple[str, ...] = tuple(STANDARD_FILE_CONTENTS.keys())

PROTECTED_FILES: tuple[str, ...] = (
    "Dockerfile",
    "entrypoint.sh",
    "Dockerfile.json",
    "description.md",
)

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


class FileNotFoundError(Exception):
    pass


class DuplicateFileError(Exception):
    pass


class ProtectedFileError(Exception):
    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _storage() -> StorageSDK:
    return StorageSDK(await get_pool())


async def _root_id(s: StorageSDK) -> UUID:
    """Résout (ou crée) le dossier racine 'Dockerfiles'."""
    node_id = await s.resolve_node(_DOCKERFILES_ROOT)
    if node_id is None:
        node_id = await s.create_folder(_DOCKERFILES_ROOT)
    return node_id


async def _dockerfile_folder_id(
    s: StorageSDK, dockerfile_id: str, *, create: bool = True
) -> UUID | None:
    """Résout (ou crée) le dossier du dockerfile sous 'Dockerfiles'."""
    root = await _root_id(s)
    node_id = await s.resolve_node(dockerfile_id, root)
    if node_id is None and create:
        node_id = await s.create_folder(dockerfile_id, root)
    return node_id


async def _resolve_file_folder(
    s: StorageSDK, folder_id: UUID, path: str, *, create_parents: bool = False
) -> tuple[UUID, str]:
    """Retourne (parent_folder_id, filename) pour un chemin relatif.

    Si le chemin contient des segments intermédiaires (ex: config/app.toml),
    crée les dossiers parents si create_parents=True.
    """
    parts = path.split("/")
    filename = parts[-1]
    parent_id = folder_id
    for segment in parts[:-1]:
        if create_parents:
            parent_id = await s.create_folder(segment, parent_id)
        else:
            found = await s.resolve_node(segment, parent_id)
            if not found:
                raise FileNotFoundError(f"Directory '{segment}' not found in path '{path}'")
            parent_id = found
    return parent_id, filename


async def _list_recursive(
    s: StorageSDK,
    folder_id: UUID,
    dockerfile_id: str,
    prefix: str = "",
    *,
    include_dirs: bool = False,
) -> list[FileSummary]:
    """Liste récursive des enfants d'un dossier en reconstruisant les chemins."""
    results: list[FileSummary] = []
    children = await s.list_folder(folder_id)
    for child in children:
        rel_path = f"{prefix}/{child['name']}" if prefix else child["name"]
        if child["kind"] == 0:
            if include_dirs:
                results.append(FileSummary(
                    id=child["id"],
                    dockerfile_id=dockerfile_id,
                    path=rel_path,
                    content="",
                    type="dir",
                    size=0,
                    created_at=child["created_at"],
                    updated_at=child["updated_at"],
                ))
            results.extend(
                await _list_recursive(s, child["id"], dockerfile_id, rel_path, include_dirs=include_dirs)
            )
        else:
            node = await s.read_node(child["id"])
            results.append(FileSummary(
                id=child["id"],
                dockerfile_id=dockerfile_id,
                path=rel_path,
                content=node["content"] or "" if node else "",
                type="file",
                size=child["size"] or 0,
                created_at=child["created_at"],
                updated_at=child["updated_at"],
            ))
    return results


async def _node_to_summary(
    s: StorageSDK, node_id: UUID, dockerfile_id: str, df_folder_id: UUID
) -> FileSummary:
    """Construit un FileSummary depuis un node_id en reconstruisant le chemin."""
    node = await s.read_node(node_id)
    if not node:
        raise FileNotFoundError(f"File {node_id} not found")

    parts = [node["name"]]
    parent_id = node["parent_id"]
    while parent_id and parent_id != df_folder_id:
        parent = await s.read_node(parent_id)
        if not parent:
            break
        parts.insert(0, parent["name"])
        parent_id = parent["parent_id"]

    return FileSummary(
        id=node_id,
        dockerfile_id=dockerfile_id,
        path="/".join(parts),
        content=node["content"] or "" if node["kind"] != 0 else "",
        type="dir" if node["kind"] == 0 else "file",
        size=node["size"] or 0,
        created_at=node["created_at"],
        updated_at=node["updated_at"],
    )


async def _find_file(file_id: UUID) -> tuple[FileSummary, UUID]:
    """Retourne (FileSummary, dockerfile_folder_id) pour un file_id."""
    s = await _storage()
    node = await s.read_node(file_id)
    if not node:
        raise FileNotFoundError(f"File {file_id} not found")

    root = await _root_id(s)

    # Remonte l'arbre pour trouver le dossier dockerfile (enfant direct de root)
    current_id = file_id
    current = node
    while current["parent_id"] and current["parent_id"] != root:
        parent = await s.read_node(current["parent_id"])
        if not parent:
            raise FileNotFoundError(f"File {file_id} not found (broken tree)")
        current_id = current["parent_id"]
        current = parent

    # current est maintenant le dossier dockerfile
    df_folder_id: UUID = current_id  # type: ignore[assignment]
    dockerfile_id: str = current["name"]

    summary = await _node_to_summary(s, file_id, dockerfile_id, df_folder_id)
    return summary, df_folder_id


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def seed_standard_files(dockerfile_id: str) -> list[FileSummary]:
    """Crée le dossier + les fichiers standard avec leur contenu par défaut.

    Idempotent — ignore les fichiers déjà présents dans le storage SDK.
    """
    s = await _storage()
    folder_id = await _dockerfile_folder_id(s, dockerfile_id, create=True)
    assert folder_id is not None
    created: list[FileSummary] = []
    for filename, default_content in STANDARD_FILE_CONTENTS.items():
        existing = await s.resolve_node(filename, folder_id)
        if existing:
            continue
        content = default_content.replace("{slug}", dockerfile_id)
        node_id = await s.write_document(folder_id, filename, content)
        node = await s.read_node(node_id)
        assert node is not None
        created.append(FileSummary(
            id=node_id,
            dockerfile_id=dockerfile_id,
            path=filename,
            content=content,
            type="file",
            size=node["size"] or 0,
            created_at=node["created_at"],
            updated_at=node["updated_at"],
        ))
        _log.info("dockerfile_files.seed", dockerfile_id=dockerfile_id, path=filename)
    return created


async def list_for_dockerfile(
    dockerfile_id: str, *, include_dirs: bool = False
) -> list[FileSummary]:
    s = await _storage()
    folder_id = await _dockerfile_folder_id(s, dockerfile_id, create=False)
    if folder_id is None:
        return []
    return await _list_recursive(s, folder_id, dockerfile_id, include_dirs=include_dirs)


async def create(
    dockerfile_id: str,
    path: str,
    content: str = "",
) -> FileSummary:
    s = await _storage()
    folder_id = await _dockerfile_folder_id(s, dockerfile_id, create=True)
    assert folder_id is not None
    parent_id, filename = await _resolve_file_folder(s, folder_id, path, create_parents=True)
    existing = await s.resolve_node(filename, parent_id)
    if existing:
        raise DuplicateFileError(f"File '{path}' already exists in dockerfile '{dockerfile_id}'")
    node_id = await s.write_document(parent_id, filename, content)
    node = await s.read_node(node_id)
    assert node is not None
    _log.info("dockerfile_files.create", dockerfile_id=dockerfile_id, path=path)
    return FileSummary(
        id=node_id,
        dockerfile_id=dockerfile_id,
        path=path,
        content=content,
        type="file",
        size=node["size"] or 0,
        created_at=node["created_at"],
        updated_at=node["updated_at"],
    )


async def get_by_id(file_id: UUID) -> FileSummary:
    summary, _ = await _find_file(file_id)
    return summary


async def update(file_id: UUID, content: str | None = None) -> FileSummary:
    if content is None:
        return await get_by_id(file_id)
    summary, df_folder_id = await _find_file(file_id)
    s = await _storage()
    parent_id, filename = await _resolve_file_folder(s, df_folder_id, summary.path)
    await s.write_document(parent_id, filename, content)
    _log.info("dockerfile_files.update", file_id=str(file_id))
    return FileSummary(
        id=file_id,
        dockerfile_id=summary.dockerfile_id,
        path=summary.path,
        content=content,
        type="file",
        size=len(content.encode("utf-8")),
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


async def delete(file_id: UUID) -> None:
    summary, _ = await _find_file(file_id)
    if summary.path in PROTECTED_FILES:
        raise ProtectedFileError(f"File '{summary.path}' is protected and cannot be deleted")
    s = await _storage()
    await s.delete_node(file_id)
    _log.info("dockerfile_files.delete", file_id=str(file_id))


async def delete_dir(dockerfile_id: str, rel_path: str) -> None:
    norm = rel_path.strip().strip("/").replace("\\", "/")
    if not norm:
        raise FileNotFoundError("Empty directory path")
    s = await _storage()
    folder_id = await _dockerfile_folder_id(s, dockerfile_id, create=False)
    if folder_id is None:
        raise FileNotFoundError(f"Dockerfile '{dockerfile_id}' has no storage folder")
    parent_id, dirname = await _resolve_file_folder(s, folder_id, norm)
    dir_id = await s.resolve_node(dirname, parent_id)
    if dir_id is None:
        raise FileNotFoundError(f"Directory '{rel_path}' not found")
    await s.delete_node(dir_id)
    _log.info("dockerfile_files.delete_dir", dockerfile_id=dockerfile_id, path=norm)


async def replace_all(
    dockerfile_id: str,
    files_map: dict[str, str],
) -> list[FileSummary]:
    """Remplace tous les fichiers d'un dockerfile par le contenu fourni.

    Supprime le dossier existant et recrée tout depuis zéro.
    """
    s = await _storage()
    root = await _root_id(s)
    existing_folder = await s.resolve_node(dockerfile_id, root)
    if existing_folder:
        await s.delete_node(existing_folder)
    folder_id = await s.create_folder(dockerfile_id, root)
    for path, content in files_map.items():
        parent_id, filename = await _resolve_file_folder(s, folder_id, path, create_parents=True)
        await s.write_document(parent_id, filename, content)
    _log.info("dockerfile_files.replace_all", dockerfile_id=dockerfile_id, file_count=len(files_map))
    return await list_for_dockerfile(dockerfile_id)


async def read_target(dockerfile_id: str) -> dict | None:
    """Lit le bloc Target de Dockerfile.json."""
    s = await _storage()
    folder_id = await _dockerfile_folder_id(s, dockerfile_id, create=False)
    if folder_id is None:
        return None
    doc = await s.read_document(folder_id, "Dockerfile.json")
    if not doc or not doc["content"]:
        return None
    try:
        return json.loads(doc["content"]).get("Target")
    except (json.JSONDecodeError, AttributeError):
        return None


async def read_generation_config(dockerfile_id: str) -> dict[str, Any]:
    """Lit le bloc Generation de Dockerfile.json avec les valeurs par défaut."""
    s = await _storage()
    folder_id = await _dockerfile_folder_id(s, dockerfile_id, create=False)

    if folder_id is None:
        return {**DEFAULT_GENERATION_CONFIG, "paths": {**DEFAULT_GENERATION_CONFIG["paths"]}}

    doc = await s.read_document(folder_id, "Dockerfile.json")
    if not doc or not doc["content"]:
        return {**DEFAULT_GENERATION_CONFIG, "paths": {**DEFAULT_GENERATION_CONFIG["paths"]}}

    try:
        data = json.loads(doc["content"])
    except json.JSONDecodeError:
        return {**DEFAULT_GENERATION_CONFIG, "paths": {**DEFAULT_GENERATION_CONFIG["paths"]}}

    gen = data.get("Generation") or {}
    result = {**DEFAULT_GENERATION_CONFIG, **gen}
    result["paths"] = {**DEFAULT_GENERATION_CONFIG["paths"], **gen.get("paths", {})}

    if "base_dir" not in gen:
        workdir = (data.get("docker", {}).get("Runtime", {}).get("WorkingDir", "") or "").strip().rstrip("/")
        if workdir:
            base = workdir.split("/")[-1]
            if base and base != DEFAULT_GENERATION_CONFIG["base_dir"]:
                result["base_dir"] = base
                result["prompt_ref_prefix"] = "@"

    return result
