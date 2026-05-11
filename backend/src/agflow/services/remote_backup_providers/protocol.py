from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


class RemoteBackupProviderError(Exception):
    """Erreur provider remote backup — propagée en 422 par les endpoints."""


@runtime_checkable
class RemoteBackupProvider(Protocol):
    async def test_connection(self, path: str) -> None:
        """Teste que le path est accessible. Lève RemoteBackupProviderError si KO."""
        ...

    async def upload_stream(
        self,
        path: str,
        filename: str,
        source: AsyncIterator[bytes],
    ) -> int:
        """Upload le stream vers path/filename. Retourne le nombre de bytes écrits."""
        ...
