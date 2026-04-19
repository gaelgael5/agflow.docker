from __future__ import annotations

import hashlib
import json
import os
import shutil
from typing import Any

import structlog

from agflow.schemas.avatars import (
    CharacterDetail,
    CharacterSummary,
    ImageInfo,
    ThemeDetail,
    ThemeSummary,
)

_log = structlog.get_logger(__name__)


def _data_dir() -> str:
    return os.path.join(os.environ.get("AGFLOW_DATA_DIR", "/app/data"), "avatars")


def _theme_dir(theme_slug: str) -> str:
    return os.path.join(_data_dir(), theme_slug)


def _char_dir(theme_slug: str, char_slug: str) -> str:
    return os.path.join(_theme_dir(theme_slug), char_slug)


def _read_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def _write_json(path: str, data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))


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


# ── Thèmes ─────────────────────────────────────────────────


def list_themes() -> list[ThemeSummary]:
    base = _data_dir()
    if not os.path.isdir(base):
        return []
    themes = []
    for name in sorted(os.listdir(base)):
        meta_path = os.path.join(base, name, "avatar.json")
        if not os.path.isfile(meta_path):
            continue
        meta = _read_json(meta_path)
        chars = _list_char_slugs(name)
        total_images = sum(_count_images(name, c) for c in chars)
        themes.append(ThemeSummary(
            slug=name,
            display_name=meta.get("display_name", name),
            description=meta.get("description", ""),
            provider=meta.get("provider", "dall-e-3"),
            character_count=len(chars),
            image_count=total_images,
        ))
    return themes


def get_theme(theme_slug: str) -> ThemeDetail:
    meta_path = os.path.join(_theme_dir(theme_slug), "avatar.json")
    if not os.path.isfile(meta_path):
        raise ThemeNotFoundError(f"Theme '{theme_slug}' not found")
    meta = _read_json(meta_path)
    chars = [get_character_summary(theme_slug, c) for c in _list_char_slugs(theme_slug)]
    total_images = sum(c.image_count for c in chars)
    return ThemeDetail(
        slug=theme_slug,
        display_name=meta.get("display_name", theme_slug),
        description=meta.get("description", ""),
        provider=meta.get("provider", "dall-e-3"),
        prompt=meta.get("prompt", ""),
        size=meta.get("size", "1024x1024"),
        quality=meta.get("quality", "hd"),
        style=meta.get("style", "vivid"),
        character_count=len(chars),
        image_count=total_images,
        characters=chars,
    )


def create_theme(
    slug: str,
    display_name: str,
    description: str,
    prompt: str,
    provider: str = "dall-e-3",
    size: str = "1024x1024",
    quality: str = "hd",
    style: str = "vivid",
) -> ThemeSummary:
    d = _theme_dir(slug)
    if os.path.isdir(d):
        raise DuplicateThemeError(f"Theme '{slug}' already exists")
    os.makedirs(d)
    _write_json(os.path.join(d, "avatar.json"), {
        "display_name": display_name,
        "description": description,
        "prompt": prompt,
        "provider": provider,
        "size": size,
        "quality": quality,
        "style": style,
    })
    _log.info("avatar.theme.create", slug=slug)
    return ThemeSummary(
        slug=slug,
        display_name=display_name,
        description=description,
        provider=provider,
        character_count=0,
        image_count=0,
    )


def update_theme(slug: str, **kwargs: Any) -> ThemeDetail:
    meta_path = os.path.join(_theme_dir(slug), "avatar.json")
    if not os.path.isfile(meta_path):
        raise ThemeNotFoundError(f"Theme '{slug}' not found")
    meta = _read_json(meta_path)
    for k, v in kwargs.items():
        if v is not None:
            meta[k] = v
    _write_json(meta_path, meta)
    _log.info("avatar.theme.update", slug=slug)
    return get_theme(slug)


def delete_theme(slug: str) -> None:
    d = _theme_dir(slug)
    if not os.path.isdir(d):
        raise ThemeNotFoundError(f"Theme '{slug}' not found")
    shutil.rmtree(d)
    _log.info("avatar.theme.delete", slug=slug)


# ── Personnages ────────────────────────────────────────────


def _list_char_slugs(theme_slug: str) -> list[str]:
    d = _theme_dir(theme_slug)
    if not os.path.isdir(d):
        return []
    return sorted(
        name for name in os.listdir(d)
        if os.path.isdir(os.path.join(d, name))
        and os.path.isfile(os.path.join(d, name, "avatar.json"))
    )


def get_character_summary(theme_slug: str, char_slug: str) -> CharacterSummary:
    meta_path = os.path.join(_char_dir(theme_slug, char_slug), "avatar.json")
    if not os.path.isfile(meta_path):
        raise CharacterNotFoundError(f"Character '{char_slug}' not found in theme '{theme_slug}'")
    meta = _read_json(meta_path)
    return CharacterSummary(
        slug=char_slug,
        display_name=meta.get("display_name", char_slug),
        description=meta.get("description", ""),
        image_count=_count_images(theme_slug, char_slug),
        selected=meta.get("selected"),
    )


def get_character(theme_slug: str, char_slug: str) -> CharacterDetail:
    meta_path = os.path.join(_char_dir(theme_slug, char_slug), "avatar.json")
    if not os.path.isfile(meta_path):
        raise CharacterNotFoundError(f"Character '{char_slug}' not found in theme '{theme_slug}'")
    meta = _read_json(meta_path)
    images = list_images(theme_slug, char_slug)
    selected = meta.get("selected")
    return CharacterDetail(
        slug=char_slug,
        display_name=meta.get("display_name", char_slug),
        description=meta.get("description", ""),
        prompt=meta.get("prompt", ""),
        image_count=len(images),
        selected=selected,
        images=images,
    )


def create_character(
    theme_slug: str,
    slug: str,
    display_name: str,
    description: str,
    prompt: str,
) -> CharacterSummary:
    if not os.path.isdir(_theme_dir(theme_slug)):
        raise ThemeNotFoundError(f"Theme '{theme_slug}' not found")
    d = _char_dir(theme_slug, slug)
    if os.path.isdir(d):
        raise DuplicateCharacterError(f"Character '{slug}' already exists in theme '{theme_slug}'")
    os.makedirs(d)
    _write_json(os.path.join(d, "avatar.json"), {
        "display_name": display_name,
        "description": description,
        "prompt": prompt,
        "selected": None,
    })
    _log.info("avatar.character.create", theme=theme_slug, slug=slug)
    return CharacterSummary(
        slug=slug,
        display_name=display_name,
        description=description,
        image_count=0,
        selected=None,
    )


def update_character(theme_slug: str, char_slug: str, **kwargs: Any) -> CharacterDetail:
    meta_path = os.path.join(_char_dir(theme_slug, char_slug), "avatar.json")
    if not os.path.isfile(meta_path):
        raise CharacterNotFoundError(f"Character '{char_slug}' not found")
    meta = _read_json(meta_path)
    for k, v in kwargs.items():
        if v is not None:
            meta[k] = v
    _write_json(meta_path, meta)
    _log.info("avatar.character.update", theme=theme_slug, slug=char_slug)
    return get_character(theme_slug, char_slug)


def delete_character(theme_slug: str, char_slug: str) -> None:
    d = _char_dir(theme_slug, char_slug)
    if not os.path.isdir(d):
        raise CharacterNotFoundError(f"Character '{char_slug}' not found")
    shutil.rmtree(d)
    _log.info("avatar.character.delete", theme=theme_slug, slug=char_slug)


# ── Images ─────────────────────────────────────────────────


def _count_images(theme_slug: str, char_slug: str) -> int:
    d = _char_dir(theme_slug, char_slug)
    if not os.path.isdir(d):
        return 0
    return len([f for f in os.listdir(d) if f.endswith(".png")])


def list_images(theme_slug: str, char_slug: str) -> list[ImageInfo]:
    d = _char_dir(theme_slug, char_slug)
    if not os.path.isdir(d):
        return []
    meta_path = os.path.join(d, "avatar.json")
    selected = None
    if os.path.isfile(meta_path):
        selected = _read_json(meta_path).get("selected")
    images = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".png"):
            continue
        num = int(f.replace(".png", ""))
        fp = os.path.join(d, f)
        images.append(ImageInfo(
            number=num,
            filename=f,
            size_bytes=os.path.getsize(fp),
            is_selected=selected == num,
        ))
    return images


def get_next_number(theme_slug: str, char_slug: str) -> int:
    images = list_images(theme_slug, char_slug)
    if not images:
        return 1
    return max(img.number for img in images) + 1


def save_image(theme_slug: str, char_slug: str, image_bytes: bytes) -> int:
    d = _char_dir(theme_slug, char_slug)
    if not os.path.isdir(d):
        raise CharacterNotFoundError(f"Character '{char_slug}' not found")

    # Check for duplicate by hash
    new_hash = hashlib.sha256(image_bytes).hexdigest()
    for fname in os.listdir(d):
        if not fname.endswith(".png"):
            continue
        existing_path = os.path.join(d, fname)
        with open(existing_path, "rb") as ef:
            if hashlib.sha256(ef.read()).hexdigest() == new_hash:
                raise DuplicateImageError(f"Cette image existe déjà ({fname})")

    num = get_next_number(theme_slug, char_slug)
    path = os.path.join(d, f"{num}.png")
    with open(path, "wb") as f:
        f.write(image_bytes)
    _log.info("avatar.image.save", theme=theme_slug, char=char_slug, number=num)
    return num


def delete_image(theme_slug: str, char_slug: str, number: int) -> None:
    path = os.path.join(_char_dir(theme_slug, char_slug), f"{number}.png")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Image {number}.png not found")
    os.remove(path)
    meta_path = os.path.join(_char_dir(theme_slug, char_slug), "avatar.json")
    if os.path.isfile(meta_path):
        meta = _read_json(meta_path)
        if meta.get("selected") == number:
            meta["selected"] = None
            _write_json(meta_path, meta)
    _log.info("avatar.image.delete", theme=theme_slug, char=char_slug, number=number)


def get_image_path(theme_slug: str, char_slug: str, number: int) -> str:
    path = os.path.join(_char_dir(theme_slug, char_slug), f"{number}.png")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Image {number}.png not found")
    return path


def select_image(theme_slug: str, char_slug: str, number: int) -> None:
    path = os.path.join(_char_dir(theme_slug, char_slug), f"{number}.png")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Image {number}.png not found")
    meta_path = os.path.join(_char_dir(theme_slug, char_slug), "avatar.json")
    meta = _read_json(meta_path)
    meta["selected"] = number
    _write_json(meta_path, meta)
    _log.info("avatar.image.select", theme=theme_slug, char=char_slug, number=number)
