from __future__ import annotations

from datetime import datetime

from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProvider,
    RemoteFile,
)


def test_remote_file_dataclass_fields():
    """RemoteFile exposes filename, size_bytes, last_modified."""
    rf = RemoteFile(filename="x.sql.gz", size_bytes=1024, last_modified=datetime(2026, 5, 1))
    assert rf.filename == "x.sql.gz"
    assert rf.size_bytes == 1024
    assert rf.last_modified == datetime(2026, 5, 1)


def test_protocol_has_list_remote_and_download_stream():
    """The Protocol exposes the new methods."""
    assert hasattr(RemoteBackupProvider, "list_remote")
    assert hasattr(RemoteBackupProvider, "download_stream")
