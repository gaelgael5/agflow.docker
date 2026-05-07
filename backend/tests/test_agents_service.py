from __future__ import annotations

import pytest

from agflow.db.pool import close_pool, fetch_all
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture(autouse=True)
async def _clean():
    await reset_schema_and_migrate()
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_migration_creates_agents_table() -> None:
    rows = await fetch_all(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'agents' ORDER BY column_name"
    )
    columns = {r["column_name"] for r in rows}
    assert "slug" in columns
    assert "id" in columns
    assert "mcp_bindings" in columns
    assert "generations" in columns
    assert "is_assistant" in columns


@pytest.mark.asyncio
async def test_migration_creates_agent_profiles_table() -> None:
    rows = await fetch_all(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'agent_profiles' ORDER BY column_name"
    )
    columns = {r["column_name"] for r in rows}
    assert "id" in columns
    assert "agent_slug" in columns
    assert "document_ids" in columns
