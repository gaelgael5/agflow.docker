from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from agflow.schemas.local_backups import LocalBackupSummary


def test_local_backup_summary_with_source_remote():
    """source_remote_connection_id is exposed and accepted."""
    remote_id = uuid4()
    dto = LocalBackupSummary(
        id=uuid4(),
        filename="x.sql.gz",
        size_bytes=1024,
        status="completed",
        created_at=datetime.now(),
        source_remote_connection_id=remote_id,
    )
    assert dto.source_remote_connection_id == remote_id


def test_local_backup_summary_source_remote_optional():
    """source_remote_connection_id defaults to None for local-dump backups."""
    dto = LocalBackupSummary(
        id=uuid4(),
        filename="x.sql.gz",
        size_bytes=1024,
        status="completed",
        created_at=datetime.now(),
    )
    assert dto.source_remote_connection_id is None
