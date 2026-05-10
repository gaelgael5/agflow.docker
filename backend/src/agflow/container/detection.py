from __future__ import annotations

import asyncpg
import structlog

from agflow.container.models import RuntimeMode
from agflow.db.pool import fetch_one

_log = structlog.get_logger(__name__)

_MODE_FILTER = "docker_standalone|docker_swarm|k3s|k8s"


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
    """Charge le mode depuis la DB (key='mode') et le valide, ou détecte à neuf."""
    row = await fetch_one(
        "SELECT value FROM runtime_config WHERE key = 'mode'"
    )
    if row is not None:
        try:
            mode = RuntimeMode(row["value"])
            if await validate_runtime(mode):
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE runtime_config SET validated_at = NOW() WHERE key = 'mode'"
                    )
                _log.info("runtime.validated", mode=mode.value)
                return mode
        except ValueError:
            pass

    mode = await detect_runtime()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO runtime_config (key, value, filter)
            VALUES ('mode', $1, $2)
            ON CONFLICT (key) DO UPDATE SET value = $1, validated_at = NOW()
            """,
            mode.value,
            _MODE_FILTER,
        )
    return mode
