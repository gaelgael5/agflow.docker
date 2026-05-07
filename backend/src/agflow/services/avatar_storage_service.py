from __future__ import annotations

import contextlib
import hashlib
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one, get_pool
from agflow.schemas.avatars import (
    CharacterDetail,
    CharacterSummary,
    ImageInfo,
    ThemeDetail,
    ThemeSummary,
)
from agflow.storage import StorageSDK

_log = structlog.get_logger(__name__)

_AVATARS_ROOT = "avatars"


class ThemeNotFoundError(Exception):
    pass


class DuplicateThemeError(Exception):
    pass


class CharacterNotFoundError(Exception):
    pass


class DuplicateCharacterError(Exception):
    pass


class DuplicateImageError(Exception):
    pass


class ImageNotFoundError(Exception):
    pass


# ── Helpers StorageSDK ────────────────────────────────────────────────────────


async def _storage() -> StorageSDK:
    return StorageSDK(await get_pool())


async def _root_id(s: StorageSDK) -> UUID:
    node_id = await s.resolve_node(_AVATARS_ROOT)
    if node_id is None:
        node_id = await s.create_folder(_AVATARS_ROOT)
    return node_id


async def _theme_folder_id(
    s: StorageSDK, theme_slug: str, *, create: bool = True
) -> UUID | None:
    root = await _root_id(s)
    node_id = await s.resolve_node(theme_slug, root)
    if node_id is None and create:
        node_id = await s.create_folder(theme_slug, root)
    return node_id


async def _char_folder_id(
    s: StorageSDK, theme_slug: str, char_slug: str, *, create: bool = True
) -> UUID | None:
    theme_folder = await _theme_folder_id(s, theme_slug, create=create)
    if theme_folder is None:
        return None
    node_id = await s.resolve_node(char_slug, theme_folder)
    if node_id is None and create:
        node_id = await s.create_folder(char_slug, theme_folder)
    return node_id


async def _count_images(s: StorageSDK, char_folder_id: UUID) -> int:
    children = await s.list_folder(char_folder_id)
    return sum(1 for c in children if c["name"].endswith(".png"))


async def _images_for_folder(
    s: StorageSDK, char_folder_id: UUID, selected: int | None
) -> list[ImageInfo]:
    children = await s.list_folder(char_folder_id)
    images = []
    for child in sorted(children, key=lambda c: c["name"]):
        if not child["name"].endswith(".png"):
            continue
        try:
            num = int(child["name"][:-4])
        except ValueError:
            continue
        images.append(ImageInfo(
            number=num,
            filename=child["name"],
            size_bytes=child["size"] or 0,
            is_selected=(selected == num),
        ))
    return images


# ── Thèmes ────────────────────────────────────────────────────────────────────


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


# ── Personnages ───────────────────────────────────────────────────────────────


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
        raise DuplicateCharacterError(f"Personnage '{slug}' existe déjà dans '{theme_slug}'") from exc
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


# ── Images ────────────────────────────────────────────────────────────────────


async def list_images(theme_slug: str, char_slug: str) -> list[ImageInfo]:
    row = await fetch_one(
        "SELECT selected_image FROM avatar_characters WHERE theme_slug = $1 AND slug = $2",
        theme_slug, char_slug,
    )
    if row is None:
        raise CharacterNotFoundError(f"Personnage '{char_slug}' introuvable")
    s = await _storage()
    cfid = await _char_folder_id(s, theme_slug, char_slug, create=False)
    if cfid is None:
        return []
    return await _images_for_folder(s, cfid, row["selected_image"])


async def save_image(theme_slug: str, char_slug: str, image_bytes: bytes) -> int:
    row = await fetch_one(
        "SELECT id FROM avatar_characters WHERE theme_slug = $1 AND slug = $2",
        theme_slug, char_slug,
    )
    if row is None:
        raise CharacterNotFoundError(f"Personnage '{char_slug}' introuvable")
    s = await _storage()
    cfid = await _char_folder_id(s, theme_slug, char_slug, create=True)
    assert cfid is not None
    new_hash = hashlib.sha256(image_bytes).hexdigest()
    children = await s.list_folder(cfid)
    for child in children:
        if not child["name"].endswith(".png"):
            continue
        node = await s.read_node(child["id"])
        if node and node["content"] and hashlib.sha256(node["content"]).hexdigest() == new_hash:
            raise DuplicateImageError(f"Cette image existe déjà ({child['name']})")
    nums = []
    for child in children:
        if child["name"].endswith(".png"):
            with contextlib.suppress(ValueError):
                nums.append(int(child["name"][:-4]))
    next_num = max(nums, default=0) + 1
    await s.write_document(cfid, f"{next_num}.png", image_bytes)
    _log.info("avatar.image.save", theme=theme_slug, char=char_slug, number=next_num)
    return next_num


async def get_image_bytes(theme_slug: str, char_slug: str, number: int) -> bytes:
    s = await _storage()
    cfid = await _char_folder_id(s, theme_slug, char_slug, create=False)
    if cfid is None:
        raise ImageNotFoundError(f"Image {number}.png introuvable")
    doc = await s.read_document(cfid, f"{number}.png")
    if doc is None or doc["content"] is None:
        raise ImageNotFoundError(f"Image {number}.png introuvable")
    return bytes(doc["content"])


async def delete_image(theme_slug: str, char_slug: str, number: int) -> None:
    row = await fetch_one(
        "SELECT id, selected_image FROM avatar_characters WHERE theme_slug = $1 AND slug = $2",
        theme_slug, char_slug,
    )
    if row is None:
        raise CharacterNotFoundError(f"Personnage '{char_slug}' introuvable")
    s = await _storage()
    cfid = await _char_folder_id(s, theme_slug, char_slug, create=False)
    if cfid is None:
        raise ImageNotFoundError(f"Image {number}.png introuvable")
    node_id = await s.resolve_node(f"{number}.png", cfid)
    if node_id is None:
        raise ImageNotFoundError(f"Image {number}.png introuvable")
    await s.delete_node(node_id)
    if row["selected_image"] == number:
        await execute(
            "UPDATE avatar_characters SET selected_image = NULL "
            "WHERE theme_slug = $1 AND slug = $2",
            theme_slug, char_slug,
        )
    _log.info("avatar.image.delete", theme=theme_slug, char=char_slug, number=number)


async def select_image(theme_slug: str, char_slug: str, number: int) -> None:
    row = await fetch_one(
        "SELECT id FROM avatar_characters WHERE theme_slug = $1 AND slug = $2",
        theme_slug, char_slug,
    )
    if row is None:
        raise CharacterNotFoundError(f"Personnage '{char_slug}' introuvable")
    s = await _storage()
    cfid = await _char_folder_id(s, theme_slug, char_slug, create=False)
    if cfid is None:
        raise ImageNotFoundError(f"Image {number}.png introuvable")
    node_id = await s.resolve_node(f"{number}.png", cfid)
    if node_id is None:
        raise ImageNotFoundError(f"Image {number}.png introuvable")
    await execute(
        "UPDATE avatar_characters SET selected_image = $3 "
        "WHERE theme_slug = $1 AND slug = $2",
        theme_slug, char_slug, number,
    )
    _log.info("avatar.image.select", theme=theme_slug, char=char_slug, number=number)
