from __future__ import annotations

import pytest

from agflow.db.pool import close_pool, fetch_all, fetch_one
from tests._db_reset import reset_schema_and_migrate


@pytest.mark.asyncio
async def test_run_migrations_creates_schema_migrations_table() -> None:
    await reset_schema_and_migrate()

    row = await fetch_one(
        "SELECT version FROM schema_migrations WHERE version = $1", "001_init"
    )
    assert row is not None
    assert row["version"] == "001_init"
    await close_pool()


@pytest.mark.asyncio
async def test_run_migrations_is_idempotent() -> None:
    await reset_schema_and_migrate()
    await reset_schema_and_migrate()

    rows = await fetch_all("SELECT version FROM schema_migrations")
    versions = [r["version"] for r in rows]
    assert versions.count("001_init") == 1
    await close_pool()


# Note : l'ancien test_consolidated_schema_creates_secrets_with_encrypted_value
# a été supprimé : la table `secrets` (et sa colonne `value_encrypted` bytea)
# n'existe plus depuis la migration vers Harpocrate. Le stockage des secrets
# plateforme est désormais dans `platform_secrets` (cf. 092_platform_secrets.sql)
# avec les valeurs sensibles déléguées au coffre Harpocrate.


@pytest.mark.asyncio
async def test_consolidated_schema_creates_roles_and_role_sections() -> None:
    await reset_schema_and_migrate()

    tables = await fetch_all(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN ('roles', 'role_sections')
        ORDER BY table_name
        """
    )
    names = [t["table_name"] for t in tables]
    assert "roles" in names
    assert "role_sections" in names
    await close_pool()


@pytest.mark.asyncio
async def test_consolidated_schema_creates_dockerfiles_tables() -> None:
    await reset_schema_and_migrate()

    rows = await fetch_all(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN ('dockerfiles', 'dockerfile_builds')
        ORDER BY table_name
        """
    )
    names = [r["table_name"] for r in rows]
    assert set(names) == {"dockerfile_builds", "dockerfiles"}
    await close_pool()


@pytest.mark.asyncio
async def test_consolidated_schema_creates_catalogs_tables() -> None:
    await reset_schema_and_migrate()

    rows = await fetch_all(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN ('discovery_services', 'mcp_servers', 'skills')
        ORDER BY table_name
        """
    )
    assert [r["table_name"] for r in rows] == [
        "discovery_services",
        "mcp_servers",
        "skills",
    ]
    await close_pool()


@pytest.mark.asyncio
async def test_consolidated_schema_supervision_columns_and_platform_config() -> None:
    await reset_schema_and_migrate()

    cols = await fetch_all(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'agents_instances'
          AND column_name IN ('last_activity_at', 'status', 'error_message')
        ORDER BY column_name
        """
    )
    by_name = {c["column_name"]: c for c in cols}

    assert "last_activity_at" in by_name
    assert by_name["last_activity_at"]["data_type"] == "timestamp with time zone"
    assert by_name["last_activity_at"]["is_nullable"] == "NO"

    assert "status" in by_name
    assert by_name["status"]["is_nullable"] == "NO"

    assert "error_message" in by_name
    assert by_name["error_message"]["is_nullable"] == "YES"

    chk = await fetch_one(
        """
        SELECT conname
        FROM pg_constraint
        WHERE conname = 'agents_instances_status_chk'
        """
    )
    assert chk is not None, "CHECK constraint on agents_instances.status missing"

    tbl = await fetch_one(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name = 'platform_config'
        """
    )
    assert tbl is not None, "platform_config table missing"

    defaults = await fetch_all(
        """
        SELECT key, value FROM platform_config
        WHERE key IN (
            'session_idle_timeout_s',
            'agent_idle_timeout_s',
            'supervision_reaper_interval_s',
            'supervision_reclaim_interval_s',
            'supervision_reclaim_stale_threshold_s'
        )
        """
    )
    seeded = {d["key"]: d["value"] for d in defaults}
    assert seeded["session_idle_timeout_s"] == "120"
    assert seeded["agent_idle_timeout_s"] == "600"
    assert seeded["supervision_reaper_interval_s"] == "20"
    assert seeded["supervision_reclaim_interval_s"] == "15"
    assert seeded["supervision_reclaim_stale_threshold_s"] == "30"
    await close_pool()
