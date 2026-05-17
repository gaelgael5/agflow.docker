"""Test de la migration 110 — git_sync_config table singleton."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from asyncpg import Connection, UniqueViolationError

from agflow.db.pool import get_pool
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    """Reset DB schema then yield a pool-acquired asyncpg connection."""
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def test_singleton_constraint_rejects_second_insert(fresh_db):
    """CHECK (id = 1) + PRIMARY KEY garantit le singleton."""
    await fresh_db.execute(
        """
        INSERT INTO git_sync_config (id, repo_url, auth_mode, auth_secret_ref)
        VALUES (1, 'https://github.com/owner/repo', 'pat_https', 'vault/git/pat')
        """
    )
    with pytest.raises(UniqueViolationError):
        await fresh_db.execute(
            """
            INSERT INTO git_sync_config (id, repo_url, auth_mode, auth_secret_ref)
            VALUES (1, 'https://github.com/other/repo', 'pat_https', 'vault/git/pat2')
            """
        )


async def test_default_values_applied(fresh_db):
    """Les colonnes avec DEFAULT sont remplies sans les passer dans l'INSERT."""
    await fresh_db.execute(
        """
        INSERT INTO git_sync_config (repo_url, auth_mode, auth_secret_ref)
        VALUES ('https://github.com/owner/repo', 'pat_https', 'vault/git/pat')
        """
    )
    row = await fresh_db.fetchrow("SELECT * FROM git_sync_config WHERE id = 1")
    assert row["id"] == 1
    assert row["branch"] == "main"
    assert row["commit_author_name"] == "agflow bot"
    assert row["commit_author_email"] == "bot@agflow.local"
    assert row["excluded_columns"] == "{}"
    assert row["selected_tables"] == "[]"
    assert row["cron_enabled"] is False
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


async def test_auth_mode_check_constraint(fresh_db):
    """auth_mode CHECK rejette les valeurs hors enum."""
    from asyncpg.exceptions import CheckViolationError

    with pytest.raises(CheckViolationError):
        await fresh_db.execute(
            """
            INSERT INTO git_sync_config (repo_url, auth_mode, auth_secret_ref)
            VALUES ('url', 'invalid_mode', 'vault/path')
            """
        )


async def test_updated_at_trigger(fresh_db):
    """Le trigger set_updated_at() met à jour updated_at à chaque UPDATE."""
    await fresh_db.execute(
        """
        INSERT INTO git_sync_config (repo_url, auth_mode, auth_secret_ref)
        VALUES ('url', 'pat_https', 'vault/path')
        """
    )
    before = await fresh_db.fetchval("SELECT updated_at FROM git_sync_config WHERE id = 1")
    await fresh_db.execute("UPDATE git_sync_config SET branch = 'develop' WHERE id = 1")
    after = await fresh_db.fetchval("SELECT updated_at FROM git_sync_config WHERE id = 1")
    assert after > before
