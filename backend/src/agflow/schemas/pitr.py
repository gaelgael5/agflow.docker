from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


BasebackupType = Literal["full", "diff", "incr"]


class PitrConfigOut(BaseModel):
    enabled: bool
    basebackup_cron: str
    basebackup_type: BasebackupType
    full_rebase_cron: str
    retention_count: int
    remote_connection_ids: list[UUID]
    updated_at: datetime


class PitrConfigUpdate(BaseModel):
    enabled: bool | None = None
    basebackup_cron: str | None = None
    basebackup_type: BasebackupType | None = None
    full_rebase_cron: str | None = None
    retention_count: int | None = Field(default=None, ge=1)
    remote_connection_ids: list[UUID] | None = None


class BasebackupPushSummary(BaseModel):
    remote_connection_id: UUID
    remote_connection_name: str
    status: Literal["pending", "pushing", "ok", "failed"]
    pushed_at: datetime | None
    error: str | None
    size_bytes: int | None


class BasebackupSummary(BaseModel):
    id: UUID
    pgbackrest_label: str
    started_at: datetime
    completed_at: datetime | None
    size_bytes: int | None
    status: Literal["running", "ok", "failed"]
    error: str | None
    recovery_window_start: datetime | None
    recovery_window_end: datetime | None
    pushes: list[BasebackupPushSummary]


class WalStatus(BaseModel):
    archiving_enabled: bool
    last_archived_at: datetime | None
    archive_lag_seconds: int | None
    wal_disk_used_bytes: int
    wal_disk_free_bytes: int


class RestoreWindow(BaseModel):
    earliest: datetime
    latest: datetime


class CloneRequest(BaseModel):
    target_time: datetime


class CloneStatus(BaseModel):
    id: UUID
    basebackup_id: UUID
    basebackup_label: str
    target_time: datetime
    status: Literal["restoring", "ready", "terminating", "terminated", "failed"]
    error: str | None
    pgweb_url: str | None
    started_at: datetime
    ready_at: datetime | None
    expires_at: datetime
    expires_in_seconds: int
