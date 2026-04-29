from __future__ import annotations

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)


async def get(key: str) -> str | None:
    row = await fetch_one("SELECT value FROM platform_config WHERE key = $1", key)
    return row["value"] if row else None


async def get_int(key: str, default: int) -> int:
    value = await get(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        _log.warning("platform_config.invalid_int", key=key, value=value, default=default)
        return default


async def get_all() -> dict[str, str]:
    rows = await fetch_all("SELECT key, value FROM platform_config ORDER BY key")
    return {r["key"]: r["value"] for r in rows}


async def set_value(key: str, value: str) -> None:
    await execute(
        """
        INSERT INTO platform_config (key, value, updated_at)
        VALUES ($1, $2, now())
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = now()
        """,
        key,
        value,
    )
    _log.info("platform_config.set", key=key)
