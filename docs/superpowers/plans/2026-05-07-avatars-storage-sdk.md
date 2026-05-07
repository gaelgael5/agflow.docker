# Avatars — Migration StorageSDK

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le stockage filesystem (`{AGFLOW_DATA_DIR}/avatars/`) par SQL (métadonnées) + StorageSDK (images PNG binaires).

**Architecture:** Deux tables SQL — `avatar_themes` (slug PK) et `avatar_characters` (FK → theme, UNIQUE theme+slug). Les images PNG sont stockées en binaire dans StorageSDK sous `avatars/{theme}/{char}/{n}.png`. L'image sélectionnée par personnage est tracée dans `avatar_characters.selected_image`.

**Tech Stack:** Python 3.12 / asyncpg / PostgreSQL 16 / StorageSDK (`agflow.storage.sdk`) / pytest-asyncio

---

## File Structure

| Action | Fichier |
|--------|---------|
| Créer | `backend/migrations/094_avatars.sql` |
| Créer | `backend/src/agflow/services/avatar_storage_service.py` |
| Créer | `backend/tests/test_avatar_storage_service.py` |
| Modifier | `backend/src/agflow/api/admin/avatars.py` — async + `Response(bytes)` |
| Supprimer | `backend/src/agflow/services/avatar_service.py` |

**Inchangés :** `schemas/avatars.py`, `services/image_generator.py`

---

### Task 1: Migration SQL — tables avatar_themes et avatar_characters

**Files:**
- Create: `backend/migrations/094_avatars.sql`

- [ ] **Step 1: Créer la migration**

```sql
-- backend/migrations/094_avatars.sql
CREATE TABLE IF NOT EXISTS avatar_themes (
    slug         VARCHAR(128) NOT NULL PRIMARY KEY,
    display_name TEXT         NOT NULL,
    description  TEXT         NOT NULL DEFAULT '',
    prompt       TEXT         NOT NULL DEFAULT '',
    provider     TEXT         NOT NULL DEFAULT 'dall-e-3',
    size         TEXT         NOT NULL DEFAULT '1024x1024',
    quality      TEXT         NOT NULL DEFAULT 'hd',
    style        TEXT         NOT NULL DEFAULT 'vivid',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TRIGGER set_updated_at_avatar_themes
    BEFORE UPDATE ON avatar_themes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS avatar_characters (
    id             UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    theme_slug     VARCHAR(128) NOT NULL REFERENCES avatar_themes(slug) ON DELETE CASCADE,
    slug           VARCHAR(128) NOT NULL,
    display_name   TEXT         NOT NULL,
    description    TEXT         NOT NULL DEFAULT '',
    prompt         TEXT         NOT NULL DEFAULT '',
    selected_image INT          DEFAULT NULL,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (theme_slug, slug)
);

CREATE TRIGGER set_updated_at_avatar_characters
    BEFORE UPDATE ON avatar_characters
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

- [ ] **Step 2: Appliquer**

```bash
cd backend && uv run python -m agflow.db.migrations
```

Expected: `migration applied: 094_avatars.sql`

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/094_avatars.sql
git commit -m "feat(db): tables avatar_themes et avatar_characters pour migration StorageSDK"
```

---

### Task 2: avatar_storage_service.py — service complet + tests

**Files:**
- Create: `backend/src/agflow/services/avatar_storage_service.py`
- Create: `backend/tests/test_avatar_storage_service.py`

- [ ] **Step 1: Écrire les tests (rouge)**

```python
# backend/tests/test_avatar_storage_service.py
from __future__ import annotations

import pytest

from agflow.db.pool import close_pool
from agflow.services import avatar_storage_service
from agflow.services.avatar_storage_service import (
    CharacterNotFoundError,
    DuplicateCharacterError,
    DuplicateImageError,
    DuplicateThemeError,
    ImageNotFoundError,
    ThemeNotFoundError,
)
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture(autouse=True)
async def _clean():
    await reset_schema_and_migrate()
    yield
    await close_pool()


# ── Thèmes ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_themes_empty() -> None:
    assert await avatar_storage_service.list_themes() == []


@pytest.mark.asyncio
async def test_create_and_list_theme() -> None:
    t = await avatar_storage_service.create_theme(
        slug="cartoon", display_name="Cartoon", description="desc",
        prompt="cartoon style",
    )
    assert t.slug == "cartoon"
    assert t.character_count == 0
    themes = await avatar_storage_service.list_themes()
    assert len(themes) == 1
    assert themes[0].slug == "cartoon"


@pytest.mark.asyncio
async def test_create_duplicate_theme_raises() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    with pytest.raises(DuplicateThemeError):
        await avatar_storage_service.create_theme("t", "T2", "", "p2")


@pytest.mark.asyncio
async def test_get_theme_not_found_raises() -> None:
    with pytest.raises(ThemeNotFoundError):
        await avatar_storage_service.get_theme("inexistant")


@pytest.mark.asyncio
async def test_update_theme() -> None:
    await avatar_storage_service.create_theme("t", "Ancien", "", "p")
    updated = await avatar_storage_service.update_theme("t", display_name="Nouveau")
    assert updated.display_name == "Nouveau"


@pytest.mark.asyncio
async def test_delete_theme() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    await avatar_storage_service.delete_theme("t")
    assert await avatar_storage_service.list_themes() == []


@pytest.mark.asyncio
async def test_delete_theme_not_found_raises() -> None:
    with pytest.raises(ThemeNotFoundError):
        await avatar_storage_service.delete_theme("inexistant")


# ── Personnages ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_character() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    c = await avatar_storage_service.create_character("t", "hero", "Hero", "", "brave")
    assert c.slug == "hero"
    assert c.image_count == 0
    assert c.selected is None


@pytest.mark.asyncio
async def test_create_character_duplicate_raises() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    await avatar_storage_service.create_character("t", "hero", "Hero", "", "brave")
    with pytest.raises(DuplicateCharacterError):
        await avatar_storage_service.create_character("t", "hero", "Hero2", "", "p")


@pytest.mark.asyncio
async def test_create_character_unknown_theme_raises() -> None:
    with pytest.raises(ThemeNotFoundError):
        await avatar_storage_service.create_character("inexistant", "hero", "H", "", "p")


@pytest.mark.asyncio
async def test_get_character_not_found_raises() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    with pytest.raises(CharacterNotFoundError):
        await avatar_storage_service.get_character("t", "inexistant")


@pytest.mark.asyncio
async def test_update_character() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    await avatar_storage_service.create_character("t", "hero", "Hero", "", "brave")
    updated = await avatar_storage_service.update_character("t", "hero", display_name="Héros")
    assert updated.display_name == "Héros"


@pytest.mark.asyncio
async def test_delete_character() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    await avatar_storage_service.create_character("t", "hero", "Hero", "", "p")
    await avatar_storage_service.delete_character("t", "hero")
    detail = await avatar_storage_service.get_theme("t")
    assert detail.character_count == 0


@pytest.mark.asyncio
async def test_delete_theme_cascades_characters() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    await avatar_storage_service.create_character("t", "hero", "H", "", "p")
    await avatar_storage_service.delete_theme("t")
    assert await avatar_storage_service.list_themes() == []


# ── Images ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_and_list_images() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    await avatar_storage_service.create_character("t", "hero", "H", "", "p")
    num = await avatar_storage_service.save_image("t", "hero", b"\x89PNG_fake_data_1")
    assert num == 1
    images = await avatar_storage_service.list_images("t", "hero")
    assert len(images) == 1
    assert images[0].number == 1
    assert images[0].is_selected is False


@pytest.mark.asyncio
async def test_second_image_gets_number_2() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    await avatar_storage_service.create_character("t", "hero", "H", "", "p")
    await avatar_storage_service.save_image("t", "hero", b"data_a")
    num2 = await avatar_storage_service.save_image("t", "hero", b"data_b")
    assert num2 == 2


@pytest.mark.asyncio
async def test_duplicate_image_raises() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    await avatar_storage_service.create_character("t", "hero", "H", "", "p")
    await avatar_storage_service.save_image("t", "hero", b"same_data")
    with pytest.raises(DuplicateImageError):
        await avatar_storage_service.save_image("t", "hero", b"same_data")


@pytest.mark.asyncio
async def test_get_image_bytes() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    await avatar_storage_service.create_character("t", "hero", "H", "", "p")
    await avatar_storage_service.save_image("t", "hero", b"image_content")
    data = await avatar_storage_service.get_image_bytes("t", "hero", 1)
    assert data == b"image_content"


@pytest.mark.asyncio
async def test_get_image_bytes_not_found_raises() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    await avatar_storage_service.create_character("t", "hero", "H", "", "p")
    with pytest.raises(ImageNotFoundError):
        await avatar_storage_service.get_image_bytes("t", "hero", 99)


@pytest.mark.asyncio
async def test_select_image() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    await avatar_storage_service.create_character("t", "hero", "H", "", "p")
    await avatar_storage_service.save_image("t", "hero", b"img")
    await avatar_storage_service.select_image("t", "hero", 1)
    char = await avatar_storage_service.get_character("t", "hero")
    assert char.selected == 1
    images = await avatar_storage_service.list_images("t", "hero")
    assert images[0].is_selected is True


@pytest.mark.asyncio
async def test_delete_image_clears_selected() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    await avatar_storage_service.create_character("t", "hero", "H", "", "p")
    await avatar_storage_service.save_image("t", "hero", b"img")
    await avatar_storage_service.select_image("t", "hero", 1)
    await avatar_storage_service.delete_image("t", "hero", 1)
    char = await avatar_storage_service.get_character("t", "hero")
    assert char.selected is None


@pytest.mark.asyncio
async def test_character_count_in_theme_summary() -> None:
    await avatar_storage_service.create_theme("t", "T", "", "p")
    await avatar_storage_service.create_character("t", "a", "A", "", "p")
    await avatar_storage_service.create_character("t", "b", "B", "", "p")
    themes = await avatar_storage_service.list_themes()
    assert themes[0].character_count == 2
```

- [ ] **Step 2: Vérifier rouge**

```bash
cd backend && uv run pytest tests/test_avatar_storage_service.py -v 2>&1 | head -20
```

Expected: FAIL — `ImportError` (module inexistant)

- [ ] **Step 3: Implémenter `avatar_storage_service.py`**

```python
# backend/src/agflow/services/avatar_storage_service.py
from __future__ import annotations

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
        if node and node["content"]:
            if hashlib.sha256(node["content"]).hexdigest() == new_hash:
                raise DuplicateImageError(f"Cette image existe déjà ({child['name']})")
    nums = []
    for child in children:
        if child["name"].endswith(".png"):
            try:
                nums.append(int(child["name"][:-4]))
            except ValueError:
                pass
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
```

- [ ] **Step 4: Lancer les tests**

```bash
cd backend && uv run pytest tests/test_avatar_storage_service.py -v 2>&1 | tail -30
```

DB sur `192.168.10.154` — si inaccessible, signaler en DONE_WITH_CONCERNS.

- [ ] **Step 5: Lint**

```bash
cd backend && uv run ruff check src/agflow/services/avatar_storage_service.py tests/test_avatar_storage_service.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/src/agflow/services/avatar_storage_service.py \
        backend/tests/test_avatar_storage_service.py
git commit -m "feat(avatars): service StorageSDK complet + tests (thèmes, personnages, images)"
```

---

### Task 3: Router async — api/admin/avatars.py

**Files:**
- Modify: `backend/src/agflow/api/admin/avatars.py`

Changements clés :
- `avatar_service.*` → `avatar_storage_service.*` (avec `await`)
- `FileResponse(path)` → `Response(content=bytes, media_type="image/png")`
- `get_image_path()` → `get_image_bytes()`

- [ ] **Step 1: Réécrire le router**

```python
# backend/src/agflow/api/admin/avatars.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.avatars import (
    CharacterCreate,
    CharacterDetail,
    CharacterSummary,
    CharacterUpdate,
    GenerateRequest,
    ThemeCreate,
    ThemeDetail,
    ThemeSummary,
    ThemeUpdate,
)
from agflow.services import ai_providers_service, avatar_storage_service, image_generator
from agflow.services.avatar_storage_service import (
    CharacterNotFoundError,
    DuplicateCharacterError,
    DuplicateImageError,
    DuplicateThemeError,
    ImageNotFoundError,
    ThemeNotFoundError,
)
from agflow.utils.swarm_secrets import get_swarm_secret

router = APIRouter(
    prefix="/api/admin/avatars",
    tags=["admin-avatars"],
    dependencies=[Depends(require_admin)],
)


# ── Thèmes ─────────────────────────────────────────────────


@router.get("", response_model=list[ThemeSummary])
async def list_themes():
    return await avatar_storage_service.list_themes()


@router.post("", response_model=ThemeSummary, status_code=status.HTTP_201_CREATED)
async def create_theme(payload: ThemeCreate):
    try:
        return await avatar_storage_service.create_theme(
            slug=payload.slug,
            display_name=payload.display_name,
            description=payload.description,
            prompt=payload.prompt,
            provider=payload.provider,
            size=payload.size,
            quality=payload.quality,
            style=payload.style,
        )
    except DuplicateThemeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{theme}", response_model=ThemeDetail)
async def get_theme(theme: str):
    try:
        return await avatar_storage_service.get_theme(theme)
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{theme}", response_model=ThemeDetail)
async def update_theme(theme: str, payload: ThemeUpdate):
    try:
        return await avatar_storage_service.update_theme(theme, **payload.model_dump(exclude_unset=True))
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{theme}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_theme(theme: str):
    try:
        await avatar_storage_service.delete_theme(theme)
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Personnages ────────────────────────────────────────────


@router.get("/{theme}/characters", response_model=list[CharacterSummary])
async def list_characters(theme: str):
    try:
        return await avatar_storage_service.list_characters(theme)
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{theme}/characters", response_model=CharacterSummary, status_code=status.HTTP_201_CREATED)
async def create_character(theme: str, payload: CharacterCreate):
    try:
        return await avatar_storage_service.create_character(
            theme_slug=theme,
            slug=payload.slug,
            display_name=payload.display_name,
            description=payload.description,
            prompt=payload.prompt,
        )
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateCharacterError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{theme}/characters/{char}", response_model=CharacterDetail)
async def get_character(theme: str, char: str):
    try:
        return await avatar_storage_service.get_character(theme, char)
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{theme}/characters/{char}", response_model=CharacterDetail)
async def update_character(theme: str, char: str, payload: CharacterUpdate):
    try:
        return await avatar_storage_service.update_character(
            theme, char, **payload.model_dump(exclude_unset=True)
        )
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{theme}/characters/{char}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_character(theme: str, char: str):
    try:
        await avatar_storage_service.delete_character(theme, char)
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Images ─────────────────────────────────────────────────


@router.get("/{theme}/characters/{char}/images")
async def list_images(theme: str, char: str):
    return await avatar_storage_service.list_images(theme, char)


@router.post("/{theme}/characters/{char}/generate")
async def generate_image(theme: str, char: str, payload: GenerateRequest | None = None):
    try:
        theme_detail = await avatar_storage_service.get_theme(theme)
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    try:
        char_detail = await avatar_storage_service.get_character(theme, char)
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    api_key = (payload.api_key if payload else None) or ""
    if not api_key:
        api_key = await ai_providers_service.resolve_api_key("image_generation", theme_detail.provider)
    if not api_key:
        api_key = get_swarm_secret("openai_api_key", env_fallback="OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucune clé API trouvée. Configurez le provider dans AI Providers ou ajoutez OPENAI_API_KEY dans les secrets.",
        )

    prompt = image_generator.build_prompt(theme_detail.prompt, char_detail.display_name, char_detail.prompt)
    provider = image_generator.get_provider(theme_detail.provider, api_key)
    try:
        image_bytes = await provider.generate(
            prompt=prompt,
            size=theme_detail.size,
            quality=theme_detail.quality,
            style=theme_detail.style,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    number = await avatar_storage_service.save_image(theme, char, image_bytes)
    return {"number": number, "size_bytes": len(image_bytes)}


@router.post("/{theme}/characters/{char}/upload")
async def upload_image(theme: str, char: str, file: UploadFile):
    try:
        await avatar_storage_service.get_character(theme, char)
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    image_bytes = await file.read()
    try:
        number = await avatar_storage_service.save_image(theme, char, image_bytes)
    except DuplicateImageError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"number": number, "size_bytes": len(image_bytes)}


@router.get("/{theme}/characters/{char}/images/{n}")
async def get_image(theme: str, char: str, n: int):
    try:
        image_bytes = await avatar_storage_service.get_image_bytes(theme, char, n)
    except ImageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(content=image_bytes, media_type="image/png")


@router.delete("/{theme}/characters/{char}/images/{n}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image(theme: str, char: str, n: int):
    try:
        await avatar_storage_service.delete_image(theme, char, n)
    except (ImageNotFoundError, CharacterNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{theme}/characters/{char}/select/{n}", status_code=status.HTTP_204_NO_CONTENT)
async def select_image(theme: str, char: str, n: int):
    try:
        await avatar_storage_service.select_image(theme, char, n)
    except (ImageNotFoundError, CharacterNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

- [ ] **Step 2: Lint**

```bash
cd backend && uv run ruff check src/agflow/api/admin/avatars.py
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/api/admin/avatars.py
git commit -m "feat(avatars): router async + Response(bytes) pour images (supprime FileResponse)"
```

---

### Task 4: Nettoyage — supprimer avatar_service.py

**Files:**
- Delete: `backend/src/agflow/services/avatar_service.py`

- [ ] **Step 1: Vérifier les imports résiduels**

```bash
cd backend && grep -r "avatar_service" src/ tests/ 2>/dev/null
```

Expected: aucun résultat.

- [ ] **Step 2: Supprimer**

```powershell
Remove-Item "backend\src\agflow\services\avatar_service.py"
```

- [ ] **Step 3: Lint global**

```bash
cd backend && uv run ruff check src/agflow/
```

- [ ] **Step 4: Commit**

```bash
git add -u
git commit -m "chore(avatars): suppression avatar_service.py (remplacé par avatar_storage_service)"
```

---

## Self-Review

**Spec coverage :**
- ✅ `avatar_themes` SQL — tous les champs (slug, display_name, description, prompt, provider, size, quality, style)
- ✅ `avatar_characters` SQL — FK cascade, UNIQUE (theme_slug, slug), selected_image INT
- ✅ StorageSDK binaire pour PNG — `write_document(cfid, f"{n}.png", bytes)`
- ✅ Détection doublons SHA256 — lecture tous nodes du dossier
- ✅ Numérotation séquentielle — max existant + 1
- ✅ Sélection image → stored in SQL column `selected_image`
- ✅ Delete image → reset selected_image si nécessaire
- ✅ Delete theme → cascade SQL characters + delete StorageSDK folder
- ✅ Router — `FileResponse` remplacé par `Response(content=bytes)`
- ✅ `image_generator.py` inchangé
- ✅ `schemas/avatars.py` inchangés

**Type consistency :** `ImageNotFoundError` utilisé de façon cohérente dans service et router. `get_image_path()` complètement remplacé par `get_image_bytes()`.
