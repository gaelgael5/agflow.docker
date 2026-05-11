from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from pathlib import PurePosixPath

import aioftp
import structlog

from agflow.services.remote_backup_providers.protocol import RemoteBackupProviderError

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
                # Vérifie l'accès en listant le répertoire parent — sans muter le serveur.
                parent = str(PurePosixPath(path).parent) if path not in ("", "/") else "/"
                await client.list(parent)
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
