"""Migration 113 — table auth_config singleton."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from asyncpg import CheckViolationError, Connection

from agflow.db.pool import get_pool
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    """Reset DB then yield an asyncpg connection."""
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def test_auth_config_table_exists(fresh_db):
    table = await fresh_db.fetchval("SELECT to_regclass('public.auth_config')")
    assert table is not None


async def test_auth_config_singleton_seeded(fresh_db):
    row = await fresh_db.fetchrow("SELECT * FROM auth_config WHERE id = 1")
    assert row is not None
    assert row["mode"] == "local"
    assert row["keycloak_url"] == ""
    assert row["keycloak_realm"] == ""
    assert row["keycloak_client_id"] == ""
    assert row["keycloak_client_secret_ref"] == ""
    assert row["vault_name"] == "default"


async def test_auth_config_check_id_rejects_second_row(fresh_db):
    """CHECK (id = 1) interdit toute autre ligne."""
    with pytest.raises(CheckViolationError):
        await fresh_db.execute("INSERT INTO auth_config (id, mode) VALUES (2, 'local')")


async def test_auth_config_check_mode_rejects_invalid(fresh_db):
    """CHECK mode rejette une valeur hors enum."""
    with pytest.raises(CheckViolationError):
        await fresh_db.execute(
            "UPDATE auth_config SET mode = 'invalid' WHERE id = 1"
        )


async def test_auth_config_updated_at_trigger(fresh_db):
    before = await fresh_db.fetchval("SELECT updated_at FROM auth_config WHERE id = 1")
    await fresh_db.execute("UPDATE auth_config SET keycloak_url = 'https://x' WHERE id = 1")
    after = await fresh_db.fetchval("SELECT updated_at FROM auth_config WHERE id = 1")
    assert after > before
