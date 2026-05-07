from __future__ import annotations

import pytest

from agflow.db.pool import close_pool
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
    await close_pool()


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
