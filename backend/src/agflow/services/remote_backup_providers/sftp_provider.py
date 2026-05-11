from __future__ import annotations

from collections.abc import AsyncIterator

import asyncssh
import structlog

from agflow.services.remote_backup_providers.protocol import RemoteBackupProviderError

_log = structlog.get_logger(__name__)
_CHUNK = 64 * 1024


class SftpProvider:
    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._host: str = config["host"]
        self._port: int = int(config.get("port", 22))
        self._fingerprint: str | None = config.get("host_key_fingerprint")
        self._username: str = credentials.get("username", "")
        self._password: str | None = credentials.get("password")
        if not self._fingerprint:
            _log.warning("sftp.host_key_check_disabled", host=self._host)
            self._known_hosts = None
        else:
            self._known_hosts = asyncssh.import_known_hosts(
                f"{self._host} {self._fingerprint}"
            )

    def _connect_kwargs(self) -> dict:
        kw: dict = {
            "host": self._host, "port": self._port,
            "username": self._username,
            "known_hosts": self._known_hosts,
        }
        if self._password:
            kw["password"] = self._password
        return kw

    async def _ensure_path(self, sftp, path: str) -> None:
        try:
            await sftp.stat(path)
            return
        except (OSError, asyncssh.Error):
            pass
        try:
            await sftp.makedirs(path, exist_ok=True)
        except (OSError, asyncssh.Error) as exc:
            cwd = await sftp.realpath(".")
            raise RemoteBackupProviderError(
                f"SFTP cannot prepare path={path!r}: {exc}. "
                f"User home (after login) is {cwd!r}."
            ) from exc

    async def test_connection(self, path: str) -> None:
        try:
            conn = await asyncssh.connect(**self._connect_kwargs())
            async with conn, conn.start_sftp_client() as sftp:
                await self._ensure_path(sftp, path)
        except RemoteBackupProviderError:
            raise
        except Exception as exc:
            raise RemoteBackupProviderError(f"SFTP test failed: {exc}") from exc

    async def upload_stream(self, path: str, filename: str, source: AsyncIterator[bytes]) -> int:
        if "/" in filename or "\\" in filename:
            raise RemoteBackupProviderError("filename must not contain path separators")
        try:
            conn = await asyncssh.connect(**self._connect_kwargs())
            async with conn, conn.start_sftp_client() as sftp:
                await self._ensure_path(sftp, path)
                remote_file = f"{path.rstrip('/')}/{filename}"
                written = 0
                f = await sftp.open(remote_file, "wb")
                async with f:
                    async for chunk in source:
                        await f.write(chunk)
                        written += len(chunk)
            _log.info("sftp.upload_done", path=remote_file, bytes=written)
            return written
        except RemoteBackupProviderError:
            raise
        except Exception as exc:
            raise RemoteBackupProviderError(f"SFTP upload failed: {exc}") from exc
