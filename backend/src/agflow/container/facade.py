from __future__ import annotations

import asyncpg
import structlog

from agflow.container.adapters.base import AbstractContainerAdapter, NoneAdapter
from agflow.container.detection import load_or_detect
from agflow.container.models import RuntimeMode

_log = structlog.get_logger(__name__)

_adapter: AbstractContainerAdapter | None = None
_mode: RuntimeMode = RuntimeMode.NONE


def get_facade() -> AbstractContainerAdapter:
    if _adapter is None:
        raise RuntimeError(
            "Container facade non initialisée — appeler init_facade() au démarrage"
        )
    return _adapter


def get_mode() -> RuntimeMode:
    return _mode


async def init_facade(pool: asyncpg.Pool) -> RuntimeMode:
    """Détecte (ou charge) le mode runtime et câble l'adapter correspondant.

    À appeler une seule fois dans le lifespan FastAPI, après les migrations.
    """
    global _adapter, _mode

    from agflow.container.adapters.docker_standalone import DockerStandaloneAdapter
    from agflow.container.adapters.docker_swarm import DockerSwarmAdapter

    mode = await load_or_detect(pool)
    _mode = mode

    if mode == RuntimeMode.DOCKER_SWARM:
        _adapter = DockerSwarmAdapter()
    elif mode == RuntimeMode.DOCKER_STANDALONE:
        _adapter = DockerStandaloneAdapter()
    else:
        _adapter = NoneAdapter()
        _log.warning("container.facade.no_runtime", mode=mode.value)

    _log.info("container.facade.ready", mode=mode.value, adapter=type(_adapter).__name__)
    return mode
