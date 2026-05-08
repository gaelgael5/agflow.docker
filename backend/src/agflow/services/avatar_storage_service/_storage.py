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


__all__ = [
    "UUID",
    "_AVATARS_ROOT",
    "Any",
    "CharacterDetail",
    "CharacterNotFoundError",
    "CharacterSummary",
    "DuplicateCharacterError",
    "DuplicateImageError",
    "DuplicateThemeError",
    "ImageInfo",
    "ImageNotFoundError",
    "StorageSDK",
    "ThemeDetail",
    "ThemeNotFoundError",
    "ThemeSummary",
    "_char_folder_id",
    "_count_images",
    "_images_for_folder",
    "_log",
    "_root_id",
    "_storage",
    "_theme_folder_id",
    "contextlib",
    "execute",
    "fetch_all",
    "fetch_one",
    "get_pool",
    "hashlib",
]
