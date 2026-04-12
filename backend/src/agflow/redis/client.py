from __future__ import annotations

import redis.asyncio as aioredis
import structlog

from agflow.config import get_settings

_log = structlog.get_logger(__name__)
_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
        _log.info("redis.connected", url=settings.redis_url)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        _log.info("redis.closed")
