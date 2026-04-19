from __future__ import annotations

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, fetch_all, get_pool
from agflow.services import agents_catalog_service


@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    yield p
    await close_pool()


@pytest.mark.asyncio
class TestAgentsCatalog:
    async def test_upsert_new_slug(self, pool) -> None:
        await agents_catalog_service.upsert("test-agent-123")
        rows = await fetch_all(
            "SELECT slug FROM agents_catalog WHERE slug = $1", "test-agent-123",
        )
        assert len(rows) == 1
        await agents_catalog_service.delete("test-agent-123")

    async def test_upsert_existing_slug_updates_last_seen(self, pool) -> None:
        await agents_catalog_service.upsert("repeat-slug")
        row1 = await fetch_all(
            "SELECT last_seen FROM agents_catalog WHERE slug = $1", "repeat-slug",
        )
        await agents_catalog_service.upsert("repeat-slug")
        row2 = await fetch_all(
            "SELECT last_seen FROM agents_catalog WHERE slug = $1", "repeat-slug",
        )
        assert row2[0]["last_seen"] >= row1[0]["last_seen"]
        await agents_catalog_service.delete("repeat-slug")

    async def test_delete(self, pool) -> None:
        await agents_catalog_service.upsert("delete-me")
        await agents_catalog_service.delete("delete-me")
        rows = await fetch_all(
            "SELECT slug FROM agents_catalog WHERE slug = $1", "delete-me",
        )
        assert rows == []

    async def test_sync_from_filesystem(self, pool, tmp_path, monkeypatch) -> None:
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "alpha").mkdir()
        (agents_dir / "beta").mkdir()
        (agents_dir / ".hidden").mkdir()

        monkeypatch.setattr(
            agents_catalog_service, "_agents_dir", lambda: agents_dir,
        )
        await agents_catalog_service.sync_from_filesystem()

        rows = await fetch_all(
            "SELECT slug FROM agents_catalog WHERE slug IN ('alpha','beta','.hidden') "
            "ORDER BY slug",
        )
        slugs = [r["slug"] for r in rows]
        assert "alpha" in slugs
        assert "beta" in slugs
        assert ".hidden" not in slugs
        await agents_catalog_service.delete("alpha")
        await agents_catalog_service.delete("beta")
