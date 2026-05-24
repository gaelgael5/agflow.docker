"""Bus in-process de logs de déploiement.

Chaque déploiement actif a une asyncio.Queue. L'executor publie dedans ;
l'endpoint SSE consomme. Scoped au processus — un seul worker uvicorn suffit.
"""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import structlog

_log = structlog.get_logger(__name__)


class DeploymentLogBus:
    def __init__(self) -> None:
        self._queues: dict[UUID, list[asyncio.Queue[Any]]] = {}

    def subscribe(self, deployment_id: UUID) -> asyncio.Queue[Any]:
        """Crée et enregistre une queue pour un consommateur SSE."""
        q: asyncio.Queue[Any] = asyncio.Queue()
        self._queues.setdefault(deployment_id, []).append(q)
        return q

    def unsubscribe(self, deployment_id: UUID, q: asyncio.Queue[Any]) -> None:
        listeners = self._queues.get(deployment_id, [])
        if q in listeners:
            listeners.remove(q)
        if not listeners:
            self._queues.pop(deployment_id, None)

    async def publish(self, deployment_id: UUID, event: dict[str, Any]) -> None:
        for q in self._queues.get(deployment_id, []):
            await q.put(event)

    async def close(self, deployment_id: UUID) -> None:
        """Envoie le sentinel None à tous les abonnés puis supprime le canal."""
        for q in self._queues.get(deployment_id, []):
            await q.put(None)
        self._queues.pop(deployment_id, None)


# Singleton applicatif — importé par l'executor et les endpoints SSE.
log_bus = DeploymentLogBus()
