from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agflow.schemas.remote_backup_files import (
    PullRequest,
    RemoteBackupFileDTO,
    RestoreResult,
)


def test_remote_backup_file_dto_serializes():
    dto = RemoteBackupFileDTO(
        filename="x.sql.gz",
        size_bytes=1024,
        last_modified=datetime(2026, 5, 1),
    )
    assert dto.filename == "x.sql.gz"
    assert dto.size_bytes == 1024


def test_pull_request_validates_filename_no_path_separator():
    PullRequest(filename="x.sql.gz")  # ok
    with pytest.raises(ValidationError, match="path separator"):
        PullRequest(filename="evil/path.sql.gz")
    with pytest.raises(ValidationError, match="path separator"):
        PullRequest(filename="..\\backup.sql.gz")


def test_pull_request_requires_filename():
    with pytest.raises(ValidationError):
        PullRequest(filename="")


def test_restore_result_serializes():
    backup_id = uuid4()
    r = RestoreResult(backup_id=backup_id, exit_code=0, output_tail="...DONE")
    assert r.backup_id == backup_id
    assert r.exit_code == 0
