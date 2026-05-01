from __future__ import annotations

from pathlib import Path

from agflow.db.migrations import run_migrations
from agflow.db.pool import execute

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


async def reset_schema_and_migrate() -> None:
    """Wipe the public schema and re-apply all migrations.

    Drops everything (tables, functions, sequences, extensions installed in
    public) then re-runs the consolidated migration to get a pristine state.
    Required because the consolidated 001_init.sql creates 41 tables — partial
    DROP-then-rerun fails with DuplicateTableError on tables left over from
    a previous test.
    """
    await execute("DROP SCHEMA IF EXISTS public CASCADE")
    await execute("CREATE SCHEMA public")
    await run_migrations(_MIGRATIONS_DIR)
