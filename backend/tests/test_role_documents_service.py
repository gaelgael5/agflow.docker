from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")

from agflow.db.pool import close_pool
from agflow.services import role_documents_service as docs
from agflow.services import roles_service
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture(autouse=True)
async def _clean():
    await reset_schema_and_migrate()
    await roles_service.create(role_id="test_role", display_name="Test")
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_document() -> None:
    doc = await docs.create(
        role_id="test_role",
        section="roles",
        name="analyse_extraction",
        content_md="# Analyse\nTu analyses...",
    )

    assert doc.role_id == "test_role"
    assert doc.section == "roles"
    assert doc.name == "analyse_extraction"
    assert doc.protected is False


@pytest.mark.asyncio
async def test_create_rejects_duplicate_name() -> None:
    await docs.create(role_id="test_role", section="missions", name="dup")
    with pytest.raises(docs.DuplicateDocumentError):
        await docs.create(role_id="test_role", section="missions", name="dup")


@pytest.mark.asyncio
async def test_list_by_role_grouped_by_section() -> None:
    await docs.create(role_id="test_role", section="roles", name="r1")
    await docs.create(role_id="test_role", section="missions", name="m1")
    await docs.create(role_id="test_role", section="competences", name="c1")

    all_docs = await docs.list_for_role("test_role")
    assert len(all_docs) == 3

    sections = [d.section for d in all_docs]
    assert "roles" in sections
    assert "missions" in sections
    assert "competences" in sections


@pytest.mark.asyncio
async def test_update_content() -> None:
    doc = await docs.create(role_id="test_role", section="roles", name="u")

    updated = await docs.update(doc.id, content_md="new content")

    assert updated.content_md == "new content"


@pytest.mark.asyncio
async def test_protected_document_cannot_be_updated() -> None:
    doc = await docs.create(
        role_id="test_role",
        section="roles",
        name="locked",
        protected=True,
    )

    with pytest.raises(docs.ProtectedDocumentError):
        await docs.update(doc.id, content_md="should fail")


@pytest.mark.asyncio
async def test_protected_document_cannot_be_deleted() -> None:
    doc = await docs.create(
        role_id="test_role",
        section="roles",
        name="locked_del",
        protected=True,
    )

    with pytest.raises(docs.ProtectedDocumentError):
        await docs.delete(doc.id)


@pytest.mark.asyncio
async def test_delete_unprotected() -> None:
    doc = await docs.create(role_id="test_role", section="roles", name="del")

    await docs.delete(doc.id)

    remaining = await docs.list_for_role("test_role")
    assert all(d.id != doc.id for d in remaining)


@pytest.mark.asyncio
async def test_document_missing_raises() -> None:
    with pytest.raises(docs.DocumentNotFoundError):
        await docs.get_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_toggle_protected_flag() -> None:
    doc = await docs.create(role_id="test_role", section="roles", name="flag")

    updated = await docs.update(doc.id, protected=True)
    assert updated.protected is True

    with pytest.raises(docs.ProtectedDocumentError):
        await docs.update(doc.id, content_md="x")

    unlocked = await docs.update(doc.id, protected=False)
    assert unlocked.protected is False
