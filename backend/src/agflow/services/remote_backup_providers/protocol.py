from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


class RemoteBackupProviderError(Exception):
    """Erreur provider remote backup — propagée en 422 par les endpoints."""


@dataclass(frozen=True)
class RemoteFile:
    """Fichier listé sur un remote. last_modified peut être None si le provider ne le fournit pas."""

    filename: str
    size_bytes: int | None
    last_modified: datetime | None


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

    async def list_remote(self, path: str) -> list[RemoteFile]:
        """Liste les fichiers présents dans path. Lève RemoteBackupProviderError si KO."""
        ...

    async def download_stream(
        self,
        path: str,
        filename: str,
    ) -> AsyncIterator[bytes]:
        """Retourne un AsyncIterator[bytes] du fichier distant. Lève RemoteBackupProviderError si KO."""
        ...
