from __future__ import annotations

import re
from pathlib import Path

import structlog

from agflow.db.pool import execute, fetch_all, get_pool

_log = structlog.get_logger(__name__)
_VERSION_RE = re.compile(r"^(\d{3,})_.*\.sql$")


async def run_migrations(migrations_dir: Path) -> list[str]:
    """Apply all SQL files in `migrations_dir` that have not yet been applied.

    Returns the list of newly applied version strings (e.g. ['001_init']).
    """
    await _ensure_bookkeeping_table()

    rows = await fetch_all("SELECT version FROM schema_migrations")
    applied_versions = {r["version"] for r in rows}

    all_files = sorted(p for p in migrations_dir.glob("*.sql") if _VERSION_RE.match(p.name))

    newly_applied: list[str] = []
    pool = await get_pool()

    for path in all_files:
        version = path.stem
        if version in applied_versions:
            continue
        sql = path.read_text(encoding="utf-8")
        _log.info("migrations.apply", version=version)
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(sql)
            await conn.execute("INSERT INTO schema_migrations(version) VALUES ($1)", version)
        newly_applied.append(version)

    return newly_applied


async def _ensure_bookkeeping_table() -> None:
    await execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def _cli() -> None:
    import asyncio

    from agflow.logging_setup import configure_logging

    configure_logging("INFO")
    migrations_dir = Path(__file__).parent.parent.parent.parent / "migrations"
    applied = asyncio.run(run_migrations(migrations_dir))
    _log.info("migrations.done", applied=applied)


if __name__ == "__main__":
    _cli()
