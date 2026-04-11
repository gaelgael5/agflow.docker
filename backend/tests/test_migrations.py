from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.68:5432/agflow"

from agflow.db.migrations import run_migrations
from agflow.db.pool import close_pool, execute, fetch_all, fetch_one

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.mark.asyncio
async def test_run_migrations_creates_schema_migrations_table() -> None:
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")

    applied = await run_migrations(_MIGRATIONS_DIR)

    assert "001_init" in applied
    row = await fetch_one("SELECT version FROM schema_migrations WHERE version = $1", "001_init")
    assert row is not None
    assert row["version"] == "001_init"
    await close_pool()


@pytest.mark.asyncio
async def test_run_migrations_is_idempotent() -> None:
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")

    first = await run_migrations(_MIGRATIONS_DIR)
    second = await run_migrations(_MIGRATIONS_DIR)

    assert "001_init" in first
    assert second == []
    rows = await fetch_all("SELECT version FROM schema_migrations")
    versions = [r["version"] for r in rows]
    assert versions.count("001_init") == 1
    await close_pool()


@pytest.mark.asyncio
async def test_migration_002_creates_secrets_table() -> None:
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")

    applied = await run_migrations(_MIGRATIONS_DIR)

    assert "001_init" in applied
    assert "002_secrets" in applied

    row = await fetch_one(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'secrets' AND column_name = 'value_encrypted'
        """
    )
    assert row is not None
    assert row["data_type"] == "bytea"
    await close_pool()


@pytest.mark.asyncio
async def test_migrations_003_and_004_create_roles_tables() -> None:
    await execute("DROP TABLE IF EXISTS dockerfile_builds CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfile_files CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfiles CASCADE")
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")

    applied = await run_migrations(_MIGRATIONS_DIR)

    assert "003_roles" in applied
    assert "004_role_documents" in applied

    tables = await fetch_all(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN ('roles', 'role_documents')
        ORDER BY table_name
        """
    )
    names = [t["table_name"] for t in tables]
    assert "roles" in names
    assert "role_documents" in names

    fk = await fetch_one(
        """
        SELECT confrelid::regclass::text AS ref
        FROM pg_constraint
        WHERE conname LIKE 'role_documents_role_id_fkey%'
        """
    )
    assert fk is not None
    assert "roles" in fk["ref"]
    await close_pool()


@pytest.mark.asyncio
async def test_migrations_007_008_009_create_dockerfiles_tables() -> None:
    for t in [
        "skills",
        "mcp_servers",
        "discovery_services",
        "dockerfile_builds",
        "dockerfile_files",
        "dockerfiles",
        "role_documents",
        "roles",
        "secrets",
        "schema_migrations",
    ]:
        await execute(f"DROP TABLE IF EXISTS {t} CASCADE")

    applied = await run_migrations(_MIGRATIONS_DIR)

    assert "007_dockerfiles" in applied
    assert "008_dockerfile_files" in applied
    assert "009_dockerfile_builds" in applied

    rows = await fetch_all(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN ('dockerfiles', 'dockerfile_files', 'dockerfile_builds')
        ORDER BY table_name
        """
    )
    names = [r["table_name"] for r in rows]
    assert set(names) == {"dockerfile_builds", "dockerfile_files", "dockerfiles"}
    await close_pool()


@pytest.mark.asyncio
async def test_migrations_010_011_012_create_catalogs_tables() -> None:
    for t in [
        "skills",
        "mcp_servers",
        "discovery_services",
        "dockerfile_builds",
        "dockerfile_files",
        "dockerfiles",
        "role_documents",
        "roles",
        "secrets",
        "schema_migrations",
    ]:
        await execute(f"DROP TABLE IF EXISTS {t} CASCADE")

    applied = await run_migrations(_MIGRATIONS_DIR)

    assert "010_discovery_services" in applied
    assert "011_mcp_servers" in applied
    assert "012_skills" in applied

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
