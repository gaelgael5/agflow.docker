"""Provider Google Drive — implémente RemoteBackupProvider.

Le paramètre `path` est ignoré par toutes les méthodes : Drive n'a pas de
sous-path interne au folder configuré. On le garde dans la signature pour
préserver le contrat Protocol commun avec sftp/s3/ftps.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import structlog
from googleapiclient.errors import HttpError

from agflow.services.remote_backup_providers import gdrive_client
from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProviderError,
    RemoteFile,
)

_log = structlog.get_logger(__name__)


class GoogleDriveProvider:
    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._folder_id: str = config["folder_id"]
        self._creds = gdrive_client.build_credentials(credentials)

    async def test_connection(self, path: str) -> None:
        def _sync() -> None:
            service = gdrive_client.build_drive_service(self._creds)
            service.files().list(
                q=f"'{self._folder_id}' in parents and trashed=false",
                pageSize=1,
                fields="files(id)",
            ).execute()

        try:
            await asyncio.to_thread(_sync)
        except HttpError as exc:
            raise RemoteBackupProviderError(
                f"gdrive test_connection failed: {exc.resp.status} {exc.reason}",
            ) from exc

    async def upload_stream(
        self, path: str, filename: str, source: AsyncIterator[bytes],
    ) -> int:
        raise NotImplementedError("Implemented in next task")

    async def list_remote(self, path: str) -> list[RemoteFile]:
        raise NotImplementedError("Implemented in next task")

    async def download_stream(
        self, path: str, filename: str,
    ) -> AsyncIterator[bytes]:
        raise NotImplementedError("Implemented in next task")
        yield b""  # pour satisfaire le type hint AsyncIterator
