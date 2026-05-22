from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import asyncssh
import structlog

from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProviderError,
    RemoteFile,
)

_log = structlog.get_logger(__name__)
_CHUNK = 64 * 1024


class SftpProvider:
    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._host: str = config["host"]
        self._port: int = int(config.get("port", 22))
        self._fingerprint: str | None = config.get("host_key_fingerprint")
        self._username: str = credentials.get("username", "")
        self._password: str | None = credentials.get("password") or None
        self._private_key: str | None = credentials.get("private_key") or None
        self._passphrase: str | None = credentials.get("passphrase") or None
        if not self._fingerprint:
            _log.warning("sftp.host_key_check_disabled", host=self._host)
            self._known_hosts = None
        else:
            self._known_hosts = asyncssh.import_known_hosts(f"{self._host} {self._fingerprint}")

    def _connect_kwargs(self) -> dict:
        kw: dict = {
            "host": self._host,
            "port": self._port,
            "username": self._username,
            "known_hosts": self._known_hosts,
        }
        if self._private_key:
            try:
                key = asyncssh.import_private_key(
                    self._private_key, passphrase=self._passphrase
                )
            except Exception as exc:
                raise RemoteBackupProviderError(
                    f"Invalid SSH private key or wrong passphrase: {exc}"
                ) from exc
            kw["client_keys"] = [key]
        elif self._password:
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
                f"SFTP cannot prepare path={path!r}: {exc}. User home (after login) is {cwd!r}."
            ) from exc

    async def test_connection(self, path: str) -> None:
        try:
            conn = await asyncssh.connect(**self._connect_kwargs())
            async with conn, conn.start_sftp_client() as sftp:
                await self._ensure_path(sftp, path)
                test_file = f"{path.rstrip('/')}/.agflow-write-test"
                try:
                    f = await sftp.open(test_file, "wb")
                    async with f:
                        await f.write(b"\x00")
                    await sftp.remove(test_file)
                except (OSError, asyncssh.Error) as exc:
                    raise RemoteBackupProviderError(
                        f"SFTP write test failed at {path!r}: {exc}"
                    ) from exc
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

    async def list_remote(self, path: str) -> list[RemoteFile]:
        try:
            conn = await asyncssh.connect(**self._connect_kwargs())
            async with conn, conn.start_sftp_client() as sftp:
                entries = await sftp.readdir(path)
                files: list[RemoteFile] = []
                for entry in entries:
                    if entry.filename in (".", ".."):
                        continue
                    full = f"{path.rstrip('/')}/{entry.filename}"
                    if not await sftp.isfile(full):
                        continue
                    mtime = (
                        datetime.fromtimestamp(entry.attrs.mtime, tz=UTC)
                        if entry.attrs.mtime
                        else None
                    )
                    files.append(
                        RemoteFile(
                            filename=entry.filename,
                            size_bytes=entry.attrs.size,
                            last_modified=mtime,
                        )
                    )
                return files
        except RemoteBackupProviderError:
            raise
        except Exception as exc:
            raise RemoteBackupProviderError(f"SFTP list failed: {exc}") from exc

    async def download_stream(self, path: str, filename: str) -> AsyncIterator[bytes]:
        """Stream chunks of the remote file.

        The SSH connection is opened lazily on first iteration.  The caller
        MUST iterate to EOF or call ``aclose()`` on the returned generator —
        abandoning it without doing so leaves the SSH connection open until
        garbage collection, which is non-deterministic.
        """
        if "/" in filename or "\\" in filename:
            raise RemoteBackupProviderError("filename must not contain path separators")
        remote_file_path = f"{path.rstrip('/')}/{filename}"

        async def _gen() -> AsyncIterator[bytes]:
            try:
                conn = await asyncssh.connect(**self._connect_kwargs())
                async with conn, conn.start_sftp_client() as sftp:
                    remote_file = await sftp.open(remote_file_path, "rb")
                    async with remote_file:
                        while True:
                            chunk = await remote_file.read(_CHUNK)
                            if not chunk:
                                return
                            yield chunk
            except RemoteBackupProviderError:
                raise
            except Exception as exc:
                raise RemoteBackupProviderError(f"SFTP download failed: {exc}") from exc

        return _gen()
