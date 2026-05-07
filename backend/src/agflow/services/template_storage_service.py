from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one, get_pool
from agflow.storage import StorageSDK

_log = structlog.get_logger(__name__)

_TEMPLATES_ROOT = "templates"


class TemplateNotFoundError(Exception):
    pass


class DuplicateTemplateError(Exception):
    pass


class TemplateFileNotFoundError(Exception):
    pass


async def _storage() -> StorageSDK:
    return StorageSDK(await get_pool())


async def _root_id(s: StorageSDK) -> UUID:
    node_id = await s.resolve_node(_TEMPLATES_ROOT)
    if node_id is None:
        node_id = await s.create_folder(_TEMPLATES_ROOT)
    return node_id


async def _template_folder_id(
    s: StorageSDK, slug: str, *, create: bool = True
) -> UUID | None:
    root = await _root_id(s)
    node_id = await s.resolve_node(slug, root)
    if node_id is None and create:
        node_id = await s.create_folder(slug, root)
    return node_id


async def _build_summary(row: dict[str, Any]) -> dict[str, Any]:
    files = await list_files(row["slug"])
    cultures = sorted(set(f["culture"] for f in files if f["culture"]))
    return {
        "slug": row["slug"],
        "display_name": row["display_name"],
        "description": row["description"],
        "cultures": cultures,
    }


async def list_all() -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT slug, display_name, description FROM templates ORDER BY slug ASC"
    )
    return [await _build_summary(dict(r)) for r in rows]


async def create(slug: str, display_name: str, description: str = "") -> dict[str, Any]:
    import asyncpg

    try:
        await execute(
            "INSERT INTO templates (slug, display_name, description) VALUES ($1, $2, $3)",
            slug,
            display_name,
            description,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateTemplateError(f"Template '{slug}' existe déjà") from exc

    s = await _storage()
    await _template_folder_id(s, slug, create=True)
    _log.info("template_storage.create", slug=slug)
    return {
        "slug": slug,
        "display_name": display_name,
        "description": description,
        "cultures": [],
    }


async def get_detail(slug: str) -> dict[str, Any]:
    row = await fetch_one(
        "SELECT slug, display_name, description FROM templates WHERE slug = $1", slug
    )
    if row is None:
        raise TemplateNotFoundError(f"Template '{slug}' introuvable")
    files = await list_files(slug)
    return {
        "slug": row["slug"],
        "display_name": row["display_name"],
        "description": row["description"],
        "files": files,
    }


async def update(
    slug: str,
    display_name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    row = await fetch_one("SELECT slug FROM templates WHERE slug = $1", slug)
    if row is None:
        raise TemplateNotFoundError(f"Template '{slug}' introuvable")

    set_clauses: list[str] = []
    params: list[Any] = [slug]

    if display_name is not None:
        params.append(display_name)
        set_clauses.append(f"display_name = ${len(params)}")
    if description is not None:
        params.append(description)
        set_clauses.append(f"description = ${len(params)}")

    if set_clauses:
        await execute(
            f"UPDATE templates SET {', '.join(set_clauses)} WHERE slug = $1",
            *params,
        )

    updated = await fetch_one(
        "SELECT slug, display_name, description FROM templates WHERE slug = $1", slug
    )
    assert updated is not None
    return await _build_summary(dict(updated))


async def delete(slug: str) -> None:
    row = await fetch_one("SELECT slug FROM templates WHERE slug = $1", slug)
    if row is None:
        raise TemplateNotFoundError(f"Template '{slug}' introuvable")

    s = await _storage()
    folder_id = await _template_folder_id(s, slug, create=False)
    if folder_id is not None:
        await s.delete_node(folder_id)

    await execute("DELETE FROM templates WHERE slug = $1", slug)
    _log.info("template_storage.delete", slug=slug)


async def list_files(slug: str) -> list[dict[str, Any]]:
    s = await _storage()
    folder_id = await _template_folder_id(s, slug, create=False)
    if folder_id is None:
        return []
    children = await s.list_folder(folder_id)
    results = []
    for child in children:
        if child["kind"] == 0:
            continue
        filename = child["name"]
        culture = filename.split(".")[0] if "." in filename else ""
        results.append(
            {
                "filename": filename,
                "culture": culture,
                "size": child["size"] or 0,
            }
        )
    return results


async def read_file(slug: str, filename: str) -> str:
    s = await _storage()
    folder_id = await _template_folder_id(s, slug, create=False)
    if folder_id is None:
        raise TemplateFileNotFoundError(f"Template '{slug}' introuvable")
    doc = await s.read_document(folder_id, filename)
    if doc is None:
        raise TemplateFileNotFoundError(
            f"Fichier '{filename}' introuvable dans '{slug}'"
        )
    return doc["content"] or ""


async def write_file(slug: str, filename: str, content: str) -> None:
    s = await _storage()
    folder_id = await _template_folder_id(s, slug, create=True)
    assert folder_id is not None
    await s.write_document(folder_id, filename, content)
    _log.info("template_storage.write_file", slug=slug, filename=filename)


async def delete_file(slug: str, filename: str) -> None:
    s = await _storage()
    folder_id = await _template_folder_id(s, slug, create=False)
    if folder_id is None:
        raise TemplateFileNotFoundError(f"Template '{slug}' introuvable")
    node_id = await s.resolve_node(filename, folder_id)
    if node_id is None:
        raise TemplateFileNotFoundError(
            f"Fichier '{filename}' introuvable dans '{slug}'"
        )
    await s.delete_node(node_id)
    _log.info("template_storage.delete_file", slug=slug, filename=filename)
