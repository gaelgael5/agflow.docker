from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.82:5432/agflow"

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
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")

    first = await run_migrations(_MIGRATIONS_DIR)
    second = await run_migrations(_MIGRATIONS_DIR)

    assert "001_init" in first
    assert second == []
    rows = await fetch_all("SELECT version FROM schema_migrations")
    versions = [r["version"] for r in rows]
    assert versions.count("001_init") == 1
    await close_pool()
