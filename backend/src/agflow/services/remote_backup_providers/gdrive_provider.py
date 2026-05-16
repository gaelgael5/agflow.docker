"""Provider Google Drive — implémente RemoteBackupProvider.

Le paramètre `path` est ignoré par toutes les méthodes : Drive n'a pas de
sous-path interne au folder configuré. On le garde dans la signature pour
préserver le contrat Protocol commun avec sftp/s3/ftps.
"""
from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncIterator

import structlog
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

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
        import os
        import tempfile

        from googleapiclient.http import MediaFileUpload

        # Streame le source dans un tmpfile (le SDK Google n'accepte qu'un FS path).
        bytes_written = 0
        with tempfile.NamedTemporaryFile(delete=False, suffix="-" + filename) as tmp:
            tmp_path = tmp.name
            async for chunk in source:
                tmp.write(chunk)
                bytes_written += len(chunk)

        def _sync_upload() -> None:
            service = gdrive_client.build_drive_service(self._creds)
            media = MediaFileUpload(tmp_path, resumable=True)
            service.files().create(
                body={"name": filename, "parents": [self._folder_id]},
                media_body=media,
                fields="id",
            ).execute()

        try:
            await asyncio.to_thread(_sync_upload)
        except HttpError as exc:
            raise RemoteBackupProviderError(
                f"gdrive upload_stream failed: {exc.resp.status} {exc.reason}",
            ) from exc
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                _log.warning("gdrive.upload_stream.tmpfile_cleanup_failed", path=tmp_path)

        _log.info(
            "gdrive.upload_stream.ok",
            filename=filename, bytes=bytes_written, folder=self._folder_id,
        )
        return bytes_written

    async def list_remote(self, path: str) -> list[RemoteFile]:
        from datetime import datetime

        def _sync() -> list[dict]:
            service = gdrive_client.build_drive_service(self._creds)
            resp = service.files().list(
                q=f"'{self._folder_id}' in parents and trashed=false",
                fields="files(id, name, size, modifiedTime)",
                pageSize=1000,
            ).execute()
            return resp.get("files", [])

        try:
            raw = await asyncio.to_thread(_sync)
        except HttpError as exc:
            raise RemoteBackupProviderError(
                f"gdrive list_remote failed: {exc.resp.status} {exc.reason}",
            ) from exc

        result: list[RemoteFile] = []
        for entry in raw:
            ts = entry.get("modifiedTime")
            last_modified = (
                datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            )
            size = int(entry["size"]) if entry.get("size") is not None else None
            result.append(RemoteFile(
                filename=entry["name"], size_bytes=size, last_modified=last_modified,
            ))
        return result

    async def download_stream(
        self, path: str, filename: str,
    ) -> AsyncIterator[bytes]:
        # Résoudre file_id depuis filename
        def _resolve_id() -> str:
            service = gdrive_client.build_drive_service(self._creds)
            resp = service.files().list(
                q=(
                    f"'{self._folder_id}' in parents and "
                    f"name='{filename}' and trashed=false"
                ),
                fields="files(id)",
                pageSize=1,
            ).execute()
            files = resp.get("files", [])
            if not files:
                raise RemoteBackupProviderError(
                    f"gdrive download_stream: file {filename!r} not found in folder",
                )
            return str(files[0]["id"])

        try:
            file_id = await asyncio.to_thread(_resolve_id)
        except HttpError as exc:
            raise RemoteBackupProviderError(
                f"gdrive download_stream resolve failed: {exc.resp.status}",
            ) from exc

        def _build_downloader() -> tuple[MediaIoBaseDownload, io.BytesIO]:
            service = gdrive_client.build_drive_service(self._creds)
            request = service.files().get_media(fileId=file_id)
            buf = io.BytesIO()
            return MediaIoBaseDownload(buf, request), buf

        downloader, buf = await asyncio.to_thread(_build_downloader)

        previous_pos = 0
        while True:
            def _step() -> tuple[bool, bytes]:
                _status, done = downloader.next_chunk()
                data = buf.getvalue()
                return done, data

            done, data = await asyncio.to_thread(_step)
            new_chunk = data[previous_pos:]
            if new_chunk:
                yield new_chunk
                previous_pos = len(data)
            if done:
                break
