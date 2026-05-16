from __future__ import annotations

import pytest

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
