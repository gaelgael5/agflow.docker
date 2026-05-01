from __future__ import annotations

import os
import shutil
from pathlib import Path

from agflow.db.migrations import run_migrations
from agflow.db.pool import execute

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


async def reset_schema_and_migrate() -> None:
    """Wipe the public schema, the AGFLOW_DATA_DIR tree, and re-run migrations.

    Drops the entire DB schema (tables, functions, sequences, extensions in
    public) then re-runs the consolidated migration on a pristine schema.
    Also wipes the filesystem root used by agents/roles/templates services.

    Required because:
    - The consolidated 001_init.sql creates 41 tables; a partial DROP-then-rerun
      fails with DuplicateTableError on tables left over from a previous test.
    - Many services (agents_service, roles_service, role_documents_service,
      role_files_service) write to AGFLOW_DATA_DIR. Without wiping that, slugs
      and role_ids leak across tests.
    """
    await execute("DROP SCHEMA IF EXISTS public CASCADE")
    await execute("CREATE SCHEMA public")
    await run_migrations(_MIGRATIONS_DIR)

    data_dir = os.environ.get("AGFLOW_DATA_DIR")
    if data_dir and os.path.isdir(data_dir):
        shutil.rmtree(data_dir, ignore_errors=True)
