"""Tests du service git_sync_service (CRUD config singleton + utils DB)."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from asyncpg import Connection

from agflow.db.pool import get_pool
from agflow.services import git_sync_service as svc
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    """Reset DB schema then yield a pool-acquired asyncpg connection."""
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@pytest.fixture(autouse=True)
async def _clean_table(fresh_db):
    await fresh_db.execute("DELETE FROM git_sync_config")
    yield


async def test_get_config_returns_none_when_empty():
    config = await svc.get_config()
    assert config is None


async def test_upsert_config_creates_singleton():
    config = await svc.upsert_config(
        repo_url="https://github.com/owner/repo",
        auth_mode="pat_https",
        auth_secret_ref="${vault://default:git/pat}",
        branch="main",
        commit_author_name="agflow bot",
        commit_author_email="bot@agflow.local",
        excluded_columns={"users": ["password_hash"]},
        selected_tables=["infra_categories"],
        cron_expr=None,
        cron_enabled=False,
    )
    assert config.repo_url == "https://github.com/owner/repo"
    assert config.selected_tables == ["infra_categories"]
    assert config.excluded_columns == {"users": ["password_hash"]}


async def test_upsert_config_updates_existing():
    await svc.upsert_config(
        repo_url="https://github.com/owner/repo",
        auth_mode="pat_https",
        auth_secret_ref="ref1",
        branch="main",
        commit_author_name="bot",
        commit_author_email="bot@local",
        excluded_columns={},
        selected_tables=["t1"],
        cron_expr=None,
        cron_enabled=False,
    )
    updated = await svc.upsert_config(
        repo_url="https://github.com/owner/repo",
        auth_mode="ssh_key",
        auth_secret_ref="ref2",
        branch="develop",
        commit_author_name="bot",
        commit_author_email="bot@local",
        excluded_columns={},
        selected_tables=["t1", "t2"],
        cron_expr="0 4 * * *",
        cron_enabled=True,
    )
    assert updated.auth_mode == "ssh_key"
    assert updated.branch == "develop"
    assert updated.selected_tables == ["t1", "t2"]
    assert updated.cron_expr == "0 4 * * *"
    assert updated.cron_enabled is True


async def test_delete_config_removes_singleton():
    await svc.upsert_config(
        repo_url="url", auth_mode="pat_https", auth_secret_ref="ref",
        branch="main", commit_author_name="b", commit_author_email="b@l",
        excluded_columns={}, selected_tables=["t1"],
        cron_expr=None, cron_enabled=False,
    )
    await svc.delete_config()
    assert await svc.get_config() is None


async def test_list_available_tables_returns_public_tables(fresh_db):
    tables = await svc.list_available_tables()
    assert isinstance(tables, list)
    assert "git_sync_config" in tables
    assert "users" in tables
    assert tables == sorted(tables)


async def test_record_export_run_ok():
    await svc.upsert_config(
        repo_url="url", auth_mode="pat_https", auth_secret_ref="ref",
        branch="main", commit_author_name="b", commit_author_email="b@l",
        excluded_columns={}, selected_tables=["t1"],
        cron_expr=None, cron_enabled=False,
    )
    await svc.record_export_run(
        status="ok", sha="abc123", error=None, tables_count=5,
    )
    config = await svc.get_config()
    assert config.last_export_status == "ok"
    assert config.last_export_sha == "abc123"
    assert config.last_export_tables_count == 5
    assert config.last_export_error is None
    assert config.last_export_at is not None


async def test_record_export_run_failed():
    await svc.upsert_config(
        repo_url="url", auth_mode="pat_https", auth_secret_ref="ref",
        branch="main", commit_author_name="b", commit_author_email="b@l",
        excluded_columns={}, selected_tables=["t1"],
        cron_expr=None, cron_enabled=False,
    )
    await svc.record_export_run(
        status="failed", sha=None, error="GitAuthError: 401", tables_count=None,
    )
    config = await svc.get_config()
    assert config.last_export_status == "failed"
    assert config.last_export_error == "GitAuthError: 401"
    assert config.last_export_sha is None


async def test_record_import_run_ok():
    await svc.upsert_config(
        repo_url="url", auth_mode="pat_https", auth_secret_ref="ref",
        branch="main", commit_author_name="b", commit_author_email="b@l",
        excluded_columns={}, selected_tables=["t1"],
        cron_expr=None, cron_enabled=False,
    )
    await svc.record_import_run(
        status="ok", error=None,
        rows_inserted=10, rows_updated=5, rows_deleted=2,
    )
    config = await svc.get_config()
    assert config.last_import_status == "ok"
    assert config.last_import_rows_inserted == 10
    assert config.last_import_rows_updated == 5
    assert config.last_import_rows_deleted == 2
