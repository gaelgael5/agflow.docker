"""DTOs Pydantic pour l'intégration métier Git Sync."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field, field_validator

AuthMode = Literal["ssh_key", "pat_https", "basic_https"]
RunStatus = Literal["ok", "failed"]


class GitSyncConfigDTO(BaseModel):
    repo_url: str
    auth_mode: AuthMode
    auth_secret_ref: str
    branch: str
    commit_author_name: str
    commit_author_email: str
    excluded_columns: dict[str, list[str]]
    selected_tables: list[str]
    cron_expr: str | None
    cron_enabled: bool
    last_export_at: datetime | None
    last_export_status: RunStatus | None
    last_export_sha: str | None
    last_export_error: str | None
    last_export_tables_count: int | None
    last_import_at: datetime | None
    last_import_status: RunStatus | None
    last_import_error: str | None
    last_import_rows_inserted: int | None
    last_import_rows_updated: int | None
    last_import_rows_deleted: int | None
    created_at: datetime
    updated_at: datetime


class GitSyncConfigUpsert(BaseModel):
    repo_url: str = Field(min_length=1)
    auth_mode: AuthMode
    auth_secret_ref: str = Field(min_length=1)
    branch: str = Field(min_length=1, default="main")
    commit_author_name: str = Field(min_length=1, default="agflow bot")
    commit_author_email: str = Field(min_length=1, default="bot@agflow.local")
    excluded_columns: dict[str, list[str]] = Field(default_factory=dict)
    selected_tables: list[str] = Field(min_length=1)
    cron_expr: str | None = None
    cron_enabled: bool = False

    @field_validator("cron_expr")
    @classmethod
    def _validate_cron(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        try:
            CronTrigger.from_crontab(v)
        except ValueError as exc:
            raise ValueError(f"invalid cron expression {v!r}: {exc}") from exc
        return v


class GitSyncTestSecretRefRequest(BaseModel):
    auth_secret_ref: str = Field(min_length=1)


class GitSyncTestSecretRefResult(BaseModel):
    ok: bool
    error: str | None = None


class GitSyncExportResult(BaseModel):
    sha: str
    tables_count: int


class GitSyncTablePreview(BaseModel):
    table: str
    to_insert: int
    to_update: int
    to_delete: int


class GitSyncImportPreviewResult(BaseModel):
    tables: list[GitSyncTablePreview]


class GitSyncImportResult(BaseModel):
    rows_inserted: int
    rows_updated: int
    rows_deleted: int


class GitSyncCommitDTO(BaseModel):
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    authored_at: datetime
    html_url: str
