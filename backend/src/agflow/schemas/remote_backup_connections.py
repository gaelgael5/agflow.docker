from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RemoteBackupConnectionSummary(BaseModel):
    id: UUID
    name: str
    kind: str  # 'sftp' | 's3' | 'ftps'
    config: dict[str, Any]
    has_credentials: bool
    created_at: datetime
    updated_at: datetime


class RemoteBackupConnectionCreate(BaseModel):
    name: str
    kind: str
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] | None = None

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: str) -> str:
        # "gdrive" est accepté ici pour retourner un 400 métier (pas 422 Pydantic)
        # depuis l'endpoint, qui redirige vers le flow OAuth dédié.
        if v not in ("sftp", "s3", "ftps", "gdrive"):
            raise ValueError("kind must be one of: sftp, s3, ftps, gdrive")
        return v


class RemoteBackupConnectionUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None


class TestConnectionRequest(BaseModel):
    """Pour POST /backup-remotes/test (creds non sauvegardés)."""
    kind: str
    config: dict[str, Any]
    credentials: dict[str, Any]
    path: str  # remote_path SFTP/FTPS ou prefix S3


class TestConnectionWithIdRequest(BaseModel):
    """Pour POST /backup-remotes/{id}/test (creds en vault)."""
    path: str
    config: dict[str, Any] | None = None  # override partiel


class TestConnectionResult(BaseModel):
    ok: bool
    error: str | None = None
    message: str | None = None
