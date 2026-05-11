from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import boto3
import structlog

from agflow.services.remote_backup_providers.protocol import RemoteBackupProviderError

_log = structlog.get_logger(__name__)


class S3CompatibleProvider:
    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._endpoint_url: str | None = config.get("endpoint_url") or None
        self._region: str = config.get("region", "us-east-1")
        self._bucket: str = config["bucket"]
        self._access_key: str = credentials["access_key_id"]
        self._secret_key: str = credentials["secret_access_key"]

    def _client(self):
        return boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
        )

    async def test_connection(self, path: str) -> None:
        try:
            client = self._client()
            key = f"{path.lstrip('/')}.agflow-test"
            await asyncio.to_thread(client.put_object, Bucket=self._bucket, Key=key, Body=b"")
            await asyncio.to_thread(client.delete_object, Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise RemoteBackupProviderError(f"S3 test failed: {exc}") from exc

    async def upload_stream(self, path: str, filename: str, source: AsyncIterator[bytes]) -> int:
        if "/" in filename or "\\" in filename:
            raise RemoteBackupProviderError("filename must not contain path separators")
        key = f"{path.lstrip('/')}{filename}"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".sql.gz")  # noqa: SIM115
        tmp_path = Path(tmp.name)
        written = 0
        try:
            try:
                async for chunk in source:
                    await asyncio.to_thread(tmp.write, chunk)
                    written += len(chunk)
            finally:
                await asyncio.to_thread(tmp.close)

            client = self._client()
            # open() is synchronous on a local temp file (no network I/O); wrapping
            # upload_fileobj in to_thread is sufficient to keep the event loop free.
            def _upload_file(path: Path, s3_client, bucket: str, s3_key: str) -> None:
                with open(path, "rb") as fobj:
                    s3_client.upload_fileobj(fobj, bucket, s3_key)

            await asyncio.to_thread(_upload_file, tmp_path, client, self._bucket, key)
            _log.info("s3.upload_done", bucket=self._bucket, key=key, bytes=written)
            return written
        except RemoteBackupProviderError:
            raise
        except Exception as exc:
            raise RemoteBackupProviderError(f"S3 upload failed: {exc}") from exc
        finally:
            await asyncio.to_thread(tmp_path.unlink, missing_ok=True)
