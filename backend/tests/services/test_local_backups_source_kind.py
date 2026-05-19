"""Tests purs de la dérivation source_kind dans local_backups _to_dto."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from agflow.services.local_backups_service import _to_dto

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _row(*, source_full: UUID | None = None) -> dict:
    return {
        "id": uuid4(),
        "filename": "b.sql.gz",
        "file_path": "/tmp/b.sql.gz",
        "size_bytes": 123,
        "status": "completed",
        "created_at": _NOW,
        "created_by_user_id": None,
        "source_schedule_full_id": source_full,
        "source_remote_connection_id": None,
    }


def test_source_kind_manual_when_both_null() -> None:
    dto = _to_dto(_row())
    assert dto.source_kind == "manual"


def test_source_kind_full_when_full_id_set() -> None:
    dto = _to_dto(_row(source_full=uuid4()))
    assert dto.source_kind == "full"


