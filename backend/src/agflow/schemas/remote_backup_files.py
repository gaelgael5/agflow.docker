from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RemoteBackupFileDTO(BaseModel):
    filename: str
    size_bytes: int | None = None
    last_modified: datetime | None = None


class PullRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)

    @field_validator("filename")
    @classmethod
    def _no_path_separator(cls, v: str) -> str:
        if "/" in v or "\\" in v:
            raise ValueError("filename must not contain path separator")
        return v


class RestoreResult(BaseModel):
    backup_id: UUID
    exit_code: int
    output_tail: str
