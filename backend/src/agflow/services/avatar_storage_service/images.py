from __future__ import annotations

import contextlib
import hashlib

from agflow.db.pool import execute, fetch_one
from agflow.schemas.avatars import ImageInfo
from agflow.services.avatar_storage_service._storage import (
    CharacterNotFoundError,
    DuplicateImageError,
    ImageNotFoundError,
    _char_folder_id,
    _images_for_folder,
    _log,
    _storage,
)


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


__all__ = [
    "delete_image",
    "get_image_bytes",
    "list_images",
    "save_image",
    "select_image",
]
