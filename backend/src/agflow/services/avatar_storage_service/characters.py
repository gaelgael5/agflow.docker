from __future__ import annotations

from typing import Any

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.avatars import CharacterDetail, CharacterSummary
from agflow.services.avatar_storage_service._storage import (
    CharacterNotFoundError,
    DuplicateCharacterError,
    ThemeNotFoundError,
    _char_folder_id,
    _count_images,
    _images_for_folder,
    _log,
    _storage,
)


async def list_characters(theme_slug: str) -> list[CharacterSummary]:
    theme_row = await fetch_one("SELECT slug FROM avatar_themes WHERE slug = $1", theme_slug)
    if theme_row is None:
        raise ThemeNotFoundError(f"Thème '{theme_slug}' introuvable")
    rows = await fetch_all(
        "SELECT slug, display_name, description, selected_image "
        "FROM avatar_characters WHERE theme_slug = $1 ORDER BY slug ASC",
        theme_slug,
    )
    s = await _storage()
    result = []
    for row in rows:
        cfid = await _char_folder_id(s, theme_slug, row["slug"], create=False)
        image_count = await _count_images(s, cfid) if cfid else 0
        result.append(CharacterSummary(
            slug=row["slug"],
            display_name=row["display_name"],
            description=row["description"],
            image_count=image_count,
            selected=row["selected_image"],
        ))
    return result


async def get_character(theme_slug: str, char_slug: str) -> CharacterDetail:
    row = await fetch_one(
        "SELECT slug, display_name, description, prompt, selected_image "
        "FROM avatar_characters WHERE theme_slug = $1 AND slug = $2",
        theme_slug, char_slug,
    )
    if row is None:
        raise CharacterNotFoundError(f"Personnage '{char_slug}' introuvable dans '{theme_slug}'")
    s = await _storage()
    cfid = await _char_folder_id(s, theme_slug, char_slug, create=False)
    images = await _images_for_folder(s, cfid, row["selected_image"]) if cfid else []
    return CharacterDetail(
        slug=row["slug"],
        display_name=row["display_name"],
        description=row["description"],
        prompt=row["prompt"],
        image_count=len(images),
        selected=row["selected_image"],
        images=images,
    )


async def create_character(
    theme_slug: str,
    slug: str,
    display_name: str,
    description: str,
    prompt: str,
) -> CharacterSummary:
    import asyncpg

    theme_row = await fetch_one("SELECT slug FROM avatar_themes WHERE slug = $1", theme_slug)
    if theme_row is None:
        raise ThemeNotFoundError(f"Thème '{theme_slug}' introuvable")
    try:
        await execute(
            "INSERT INTO avatar_characters (theme_slug, slug, display_name, description, prompt) "
            "VALUES ($1, $2, $3, $4, $5)",
            theme_slug, slug, display_name, description, prompt,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateCharacterError(
            f"Personnage '{slug}' existe déjà dans '{theme_slug}'"
        ) from exc
    s = await _storage()
    await _char_folder_id(s, theme_slug, slug, create=True)
    _log.info("avatar.character.create", theme=theme_slug, slug=slug)
    return CharacterSummary(
        slug=slug, display_name=display_name, description=description,
        image_count=0, selected=None,
    )


async def update_character(theme_slug: str, char_slug: str, **kwargs: Any) -> CharacterDetail:
    row = await fetch_one(
        "SELECT id FROM avatar_characters WHERE theme_slug = $1 AND slug = $2",
        theme_slug, char_slug,
    )
    if row is None:
        raise CharacterNotFoundError(f"Personnage '{char_slug}' introuvable dans '{theme_slug}'")
    allowed = {"display_name", "description", "prompt"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if updates:
        set_clauses: list[str] = []
        params: list[Any] = [theme_slug, char_slug]
        for col, val in updates.items():
            params.append(val)
            set_clauses.append(f"{col} = ${len(params)}")
        await execute(
            f"UPDATE avatar_characters SET {', '.join(set_clauses)} "
            "WHERE theme_slug = $1 AND slug = $2",
            *params,
        )
    _log.info("avatar.character.update", theme=theme_slug, slug=char_slug)
    return await get_character(theme_slug, char_slug)


async def delete_character(theme_slug: str, char_slug: str) -> None:
    row = await fetch_one(
        "SELECT id FROM avatar_characters WHERE theme_slug = $1 AND slug = $2",
        theme_slug, char_slug,
    )
    if row is None:
        raise CharacterNotFoundError(f"Personnage '{char_slug}' introuvable dans '{theme_slug}'")
    s = await _storage()
    cfid = await _char_folder_id(s, theme_slug, char_slug, create=False)
    if cfid:
        await s.delete_node(cfid)
    await execute(
        "DELETE FROM avatar_characters WHERE theme_slug = $1 AND slug = $2",
        theme_slug, char_slug,
    )
    _log.info("avatar.character.delete", theme=theme_slug, slug=char_slug)


__all__ = [
    "create_character",
    "delete_character",
    "get_character",
    "list_characters",
    "update_character",
]
