from __future__ import annotations

import os
from pathlib import Path

import structlog

from agflow.db.pool import execute

_log = structlog.get_logger(__name__)


def _agents_dir() -> Path:
    return Path(os.environ.get("AGFLOW_DATA_DIR", "/app/data")) / "agents"


async def upsert(slug: str) -> None:
    await execute(
        "INSERT INTO agents_catalog (slug) VALUES ($1) "
        "ON CONFLICT (slug) DO UPDATE SET last_seen = now()",
        slug,
    )


async def delete(slug: str) -> None:
    await execute("DELETE FROM agents_catalog WHERE slug = $1", slug)


async def sync_from_filesystem() -> int:
    agents_dir = _agents_dir()
    if not agents_dir.is_dir():
        _log.warning("agents_catalog.sync.no_dir", path=str(agents_dir))
        return 0
    count = 0
    for entry in agents_dir.iterdir():
        if not entry.is_dir():
            continue
        slug = entry.name
        if slug.startswith(".") or slug.startswith("_"):
            continue
        await upsert(slug)
        count += 1
    _log.info("agents_catalog.sync.done", count=count)
    return count
