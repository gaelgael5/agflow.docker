from __future__ import annotations

import asyncpg
import structlog

from agflow.container.models import RuntimeMode
from agflow.db.pool import fetch_one

_log = structlog.get_logger(__name__)


async def _probe_docker() -> RuntimeMode | None:
    """Tente de joindre le socket Docker et détermine si Swarm est actif."""
    try:
        import aiodocker

        docker = aiodocker.Docker()
        try:
            await docker.version()
            try:
                await docker.services.list()
                return RuntimeMode.DOCKER_SWARM
            except aiodocker.exceptions.DockerError as exc:
                if exc.status == 503:
                    return RuntimeMode.DOCKER_STANDALONE
                raise
        finally:
            await docker.close()
    except Exception:
        return None


async def detect_runtime() -> RuntimeMode:
    """Sonde les runtimes disponibles et retourne le mode détecté."""
    mode = await _probe_docker()
    if mode is not None:
        _log.info("runtime.detected", mode=mode.value)
        return mode
    _log.warning("runtime.detected", mode=RuntimeMode.NONE.value)
    return RuntimeMode.NONE


async def validate_runtime(mode: RuntimeMode) -> bool:
    """Vérifie que le runtime stocké en base est toujours accessible."""
    if mode in (RuntimeMode.DOCKER_STANDALONE, RuntimeMode.DOCKER_SWARM):
        try:
            import aiodocker

            docker = aiodocker.Docker()
            try:
                await docker.version()
                return True
            finally:
                await docker.close()
        except Exception:
            return False
    return False


async def load_or_detect(pool: asyncpg.Pool) -> RuntimeMode:
    """Charge le mode depuis la DB et le valide, ou détecte à neuf si absent."""
    row = await fetch_one(
        "SELECT id, mode FROM runtime_config ORDER BY id DESC LIMIT 1"
    )
    if row is not None:
        try:
            mode = RuntimeMode(row["mode"])
            if await validate_runtime(mode):
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE runtime_config SET validated_at = NOW() WHERE id = $1",
                        row["id"],
                    )
                _log.info("runtime.validated", mode=mode.value)
                return mode
        except ValueError:
            pass

    mode = await detect_runtime()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO runtime_config (mode) VALUES ($1)", mode.value
        )
    return mode
