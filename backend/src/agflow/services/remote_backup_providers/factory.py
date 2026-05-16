from __future__ import annotations

from agflow.services.remote_backup_providers.ftps_provider import FtpsProvider
from agflow.services.remote_backup_providers.gdrive_provider import GoogleDriveProvider
from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProvider,
    RemoteBackupProviderError,
)
from agflow.services.remote_backup_providers.s3_provider import S3CompatibleProvider
from agflow.services.remote_backup_providers.sftp_provider import SftpProvider


def get_provider(kind: str, config: dict, credentials: dict) -> RemoteBackupProvider:
    match kind:
        case "sftp":
            return SftpProvider(config=config, credentials=credentials)
        case "ftps":
            return FtpsProvider(config=config, credentials=credentials)
        case "s3":
            return S3CompatibleProvider(config=config, credentials=credentials)
        case "gdrive":
            return GoogleDriveProvider(config=config, credentials=credentials)
        case _:
            raise RemoteBackupProviderError(f"Unknown kind: {kind!r}")
