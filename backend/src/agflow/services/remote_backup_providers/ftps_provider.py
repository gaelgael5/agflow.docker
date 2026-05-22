from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import PurePosixPath

import aioftp
import structlog

from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProviderError,
    RemoteFile,
)

_log = structlog.get_logger(__name__)


class FtpsProvider:
    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._host: str = config["host"]
        self._port: int = int(config.get("port", 21))
        self._use_tls: bool = config.get("use_tls", True)
        self._username: str = credentials.get("username", "")
        self._password: str = credentials.get("password", "")

    def _ssl_context(self) -> ssl.SSLContext | None:
        if not self._use_tls:
            return None
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _log.warning("ftps.tls_verification_disabled", host=self._host)
        return ctx

    async def test_connection(self, path: str) -> None:
        try:
            async with aioftp.Client.context(
                self._host, port=self._port, ssl=self._ssl_context()
            ) as client:
                await client.login(self._username, self._password)
                parent = str(PurePosixPath(path).parent) if path not in ("", "/") else "/"
                await client.list(parent)
                test_path = f"{path.rstrip('/')}/.agflow-write-test"

                async def _one_byte() -> AsyncIterator[bytes]:
                    yield b"\x00"

                await client.upload_stream(_one_byte(), test_path)
                await client.remove(test_path)
        except RemoteBackupProviderError:
            raise
        except Exception as exc:
            raise RemoteBackupProviderError(f"FTPS test failed: {exc}") from exc

    async def upload_stream(self, path: str, filename: str, source: AsyncIterator[bytes]) -> int:
        if "/" in filename or "\\" in filename:
            raise RemoteBackupProviderError("filename must not contain path separators")
        try:
            async with aioftp.Client.context(
                self._host, port=self._port, ssl=self._ssl_context()
            ) as client:
                await client.login(self._username, self._password)
                remote_path = f"{path.rstrip('/')}/{filename}"
                written = 0

                async def _gen():
                    nonlocal written
                    async for chunk in source:
                        written += len(chunk)
                        yield chunk

                await client.upload_stream(_gen(), remote_path)
            _log.info("ftps.upload_done", path=remote_path, bytes=written)
            return written
        except RemoteBackupProviderError:
            raise
        except Exception as exc:
            raise RemoteBackupProviderError(f"FTPS upload failed: {exc}") from exc

    @staticmethod
    def _parse_modify(modify: str | None) -> datetime | None:
        """aioftp expose 'modify' au format YYYYMMDDHHMMSS (sans timezone)."""
        if not modify or len(modify) < 14:
            return None
        try:
            return datetime.strptime(modify[:14], "%Y%m%d%H%M%S")
        except ValueError:
            return None

    async def list_remote(self, path: str) -> list[RemoteFile]:
        try:
            async with aioftp.Client.context(
                self._host, port=self._port, ssl=self._ssl_context()
            ) as client:
                await client.login(self._username, self._password)
                entries = await client.list(path)
                files: list[RemoteFile] = []
                for entry_path, info in entries:
                    if info.get("type") != "file":
                        continue
                    name = entry_path.parts[-1]
                    files.append(
                        RemoteFile(
                            filename=name,
                            size_bytes=int(info["size"]) if "size" in info else None,
                            last_modified=self._parse_modify(info.get("modify")),
                        )
                    )
                return files
        except RemoteBackupProviderError:
            raise
        except Exception as exc:
            raise RemoteBackupProviderError(f"FTPS list failed: {exc}") from exc

    async def download_stream(self, path: str, filename: str) -> AsyncIterator[bytes]:
        """Stream chunks of the remote file.

        The FTPS connection is opened lazily on first iteration.  The caller
        MUST iterate to EOF or call ``aclose()`` on the returned generator —
        abandoning it without doing so leaves the FTPS connection open until
        garbage collection, which is non-deterministic.
        """
        if "/" in filename or "\\" in filename:
            raise RemoteBackupProviderError("filename must not contain path separators")
        remote_path = f"{path.rstrip('/')}/{filename}"

        async def _gen() -> AsyncIterator[bytes]:
            try:
                async with aioftp.Client.context(
                    self._host, port=self._port, ssl=self._ssl_context()
                ) as client:
                    await client.login(self._username, self._password)
                    async with client.download_stream(remote_path) as stream:
                        async for block in stream.iter_by_block(64 * 1024):
                            yield block
            except RemoteBackupProviderError:
                raise
            except Exception as exc:
                raise RemoteBackupProviderError(f"FTPS download failed: {exc}") from exc

        return _gen()
