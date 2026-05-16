from __future__ import annotations

import pytest

from agflow.services import template_storage_service
from agflow.services.template_storage_service import (
    DuplicateTemplateError,
    TemplateNotFoundError,
)
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture(autouse=True)
async def _clean():
    await reset_schema_and_migrate()
    yield


@pytest.mark.asyncio
async def test_list_all_empty() -> None:
    result = await template_storage_service.list_all()
    assert result == []


@pytest.mark.asyncio
async def test_create_and_list() -> None:
    summary = await template_storage_service.create("base-agent", "Agent de base", "desc")
    assert summary["slug"] == "base-agent"
    assert summary["display_name"] == "Agent de base"
    assert summary["cultures"] == []

    all_templates = await template_storage_service.list_all()
    assert len(all_templates) == 1
    assert all_templates[0]["slug"] == "base-agent"


@pytest.mark.asyncio
async def test_create_duplicate_raises() -> None:
    await template_storage_service.create("tpl", "T", "")
    with pytest.raises(DuplicateTemplateError):
        await template_storage_service.create("tpl", "T2", "")


@pytest.mark.asyncio
async def test_update_display_name() -> None:
    await template_storage_service.create("tpl", "Ancien nom", "")
    result = await template_storage_service.update("tpl", display_name="Nouveau nom")
    assert result["display_name"] == "Nouveau nom"
    assert result["description"] == ""


@pytest.mark.asyncio
async def test_update_not_found_raises() -> None:
    with pytest.raises(TemplateNotFoundError):
        await template_storage_service.update("inexistant", display_name="X")


@pytest.mark.asyncio
async def test_delete() -> None:
    await template_storage_service.create("tpl", "T", "")
    await template_storage_service.delete("tpl")
    assert await template_storage_service.list_all() == []


@pytest.mark.asyncio
async def test_delete_not_found_raises() -> None:
    with pytest.raises(TemplateNotFoundError):
        await template_storage_service.delete("inexistant")


@pytest.mark.asyncio
async def test_write_and_read_file() -> None:
    await template_storage_service.create("tpl", "T", "")
    await template_storage_service.write_file("tpl", "fr.md.j2", "Bonjour {{ name }}")
    content = await template_storage_service.read_file("tpl", "fr.md.j2")
    assert content == "Bonjour {{ name }}"


@pytest.mark.asyncio
async def test_list_files_returns_culture() -> None:
    await template_storage_service.create("tpl", "T", "")
    await template_storage_service.write_file("tpl", "fr.md.j2", "")
    await template_storage_service.write_file("tpl", "en.md.j2", "")
    files = await template_storage_service.list_files("tpl")
    filenames = [f["filename"] for f in files]
    assert "fr.md.j2" in filenames
    assert "en.md.j2" in filenames
    cultures = [f["culture"] for f in files]
    assert "fr" in cultures and "en" in cultures


@pytest.mark.asyncio
async def test_cultures_reflected_in_list_all() -> None:
    await template_storage_service.create("tpl", "T", "")
    await template_storage_service.write_file("tpl", "fr.md.j2", "")
    summaries = await template_storage_service.list_all()
    assert summaries[0]["cultures"] == ["fr"]


@pytest.mark.asyncio
async def test_read_file_not_found_raises() -> None:
    await template_storage_service.create("tpl", "T", "")
    with pytest.raises(template_storage_service.TemplateFileNotFoundError):
        await template_storage_service.read_file("tpl", "inexistant.j2")


@pytest.mark.asyncio
async def test_delete_file() -> None:
    await template_storage_service.create("tpl", "T", "")
    await template_storage_service.write_file("tpl", "fr.md.j2", "contenu")
    await template_storage_service.delete_file("tpl", "fr.md.j2")
    with pytest.raises(template_storage_service.TemplateFileNotFoundError):
        await template_storage_service.read_file("tpl", "fr.md.j2")


@pytest.mark.asyncio
async def test_delete_file_not_found_raises() -> None:
    await template_storage_service.create("tpl", "T", "")
    with pytest.raises(template_storage_service.TemplateFileNotFoundError):
        await template_storage_service.delete_file("tpl", "inexistant.j2")


@pytest.mark.asyncio
async def test_delete_template_removes_files() -> None:
    await template_storage_service.create("tpl", "T", "")
    await template_storage_service.write_file("tpl", "fr.md.j2", "bonjour")
    await template_storage_service.delete("tpl")
    assert await template_storage_service.list_all() == []
