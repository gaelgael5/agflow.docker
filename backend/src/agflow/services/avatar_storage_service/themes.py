from __future__ import annotations

from typing import Any

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.avatars import CharacterSummary, ThemeDetail, ThemeSummary
from agflow.services.avatar_storage_service._storage import (
    DuplicateThemeError,
    ThemeNotFoundError,
    _char_folder_id,
    _count_images,
    _log,
    _storage,
    _theme_folder_id,
)


async def list_themes() -> list[ThemeSummary]:
    rows = await fetch_all(
        "SELECT slug, display_name, description, provider FROM avatar_themes ORDER BY slug ASC"
    )
    s = await _storage()
    result = []
    for row in rows:
        char_rows = await fetch_all(
            "SELECT slug FROM avatar_characters WHERE theme_slug = $1", row["slug"]
        )
        total_images = 0
        for cr in char_rows:
            cfid = await _char_folder_id(s, row["slug"], cr["slug"], create=False)
            if cfid:
                total_images += await _count_images(s, cfid)
        result.append(ThemeSummary(
            slug=row["slug"],
            display_name=row["display_name"],
            description=row["description"],
            provider=row["provider"],
            character_count=len(char_rows),
            image_count=total_images,
        ))
    return result


async def get_theme(theme_slug: str) -> ThemeDetail:
    row = await fetch_one(
        "SELECT slug, display_name, description, prompt, provider, size, quality, style "
        "FROM avatar_themes WHERE slug = $1",
        theme_slug,
    )
    if row is None:
        raise ThemeNotFoundError(f"Thème '{theme_slug}' introuvable")
    s = await _storage()
    char_rows = await fetch_all(
        "SELECT slug, display_name, description, selected_image "
        "FROM avatar_characters WHERE theme_slug = $1 ORDER BY slug ASC",
        theme_slug,
    )
    characters = []
    total_images = 0
    for cr in char_rows:
        cfid = await _char_folder_id(s, theme_slug, cr["slug"], create=False)
        image_count = await _count_images(s, cfid) if cfid else 0
        total_images += image_count
        characters.append(CharacterSummary(
            slug=cr["slug"],
            display_name=cr["display_name"],
            description=cr["description"],
            image_count=image_count,
            selected=cr["selected_image"],
        ))
    return ThemeDetail(
        slug=row["slug"],
        display_name=row["display_name"],
        description=row["description"],
        provider=row["provider"],
        prompt=row["prompt"],
        size=row["size"],
        quality=row["quality"],
        style=row["style"],
        character_count=len(characters),
        image_count=total_images,
        characters=characters,
    )


async def create_theme(
    slug: str,
    display_name: str,
    description: str,
    prompt: str,
    provider: str = "dall-e-3",
    size: str = "1024x1024",
    quality: str = "hd",
    style: str = "vivid",
) -> ThemeSummary:
    import asyncpg

    try:
        await execute(
            "INSERT INTO avatar_themes "
            "(slug, display_name, description, prompt, provider, size, quality, style) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            slug, display_name, description, prompt, provider, size, quality, style,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateThemeError(f"Thème '{slug}' existe déjà") from exc
    s = await _storage()
    await _theme_folder_id(s, slug, create=True)
    _log.info("avatar.theme.create", slug=slug)
    return ThemeSummary(
        slug=slug, display_name=display_name, description=description,
        provider=provider, character_count=0, image_count=0,
    )


async def update_theme(theme_slug: str, **kwargs: Any) -> ThemeDetail:
    row = await fetch_one("SELECT slug FROM avatar_themes WHERE slug = $1", theme_slug)
    if row is None:
        raise ThemeNotFoundError(f"Thème '{theme_slug}' introuvable")
    allowed = {"display_name", "description", "prompt", "provider", "size", "quality", "style"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if updates:
        set_clauses: list[str] = []
        params: list[Any] = [theme_slug]
        for col, val in updates.items():
            params.append(val)
            set_clauses.append(f"{col} = ${len(params)}")
        await execute(
            f"UPDATE avatar_themes SET {', '.join(set_clauses)} WHERE slug = $1", *params
        )
    _log.info("avatar.theme.update", slug=theme_slug)
    return await get_theme(theme_slug)


async def delete_theme(theme_slug: str) -> None:
    row = await fetch_one("SELECT slug FROM avatar_themes WHERE slug = $1", theme_slug)
    if row is None:
        raise ThemeNotFoundError(f"Thème '{theme_slug}' introuvable")
    s = await _storage()
    folder_id = await _theme_folder_id(s, theme_slug, create=False)
    if folder_id:
        await s.delete_node(folder_id)
    await execute("DELETE FROM avatar_themes WHERE slug = $1", theme_slug)
    _log.info("avatar.theme.delete", slug=theme_slug)


__all__ = [
    "create_theme",
    "delete_theme",
    "get_theme",
    "list_themes",
    "update_theme",
]
