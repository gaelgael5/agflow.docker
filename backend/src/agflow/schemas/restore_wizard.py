# backend/src/agflow/schemas/restore_wizard.py
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class VaultRef(BaseModel):
    url: str
    api_key: str


class VaultTestRequest(BaseModel):
    url: str
    api_key: str


class VaultSecretItem(BaseModel):
    name: str
    tags: list[str]


class RemoteBrowseRequest(BaseModel):
    connection_type: Literal["sftp", "s3", "ftps", "gdrive"]
    manual_fields: dict[str, str]
    vault_mappings: dict[str, str]  # field_name → vault secret name
    vault: VaultRef
    path: str = "/"


class RemoteEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None
    modified_at: datetime | None


class RestoreExecuteRequest(BaseModel):
    connection_type: Literal["sftp", "s3", "ftps", "gdrive"]
    manual_fields: dict[str, str]
    vault_mappings: dict[str, str]
    vault: VaultRef
    file_path: str  # chemin complet du fichier sur le remote


class RestoreJobStarted(BaseModel):
    job_id: UUID


class RestoreJobStatus(BaseModel):
    job_id: UUID
    status: Literal["running", "done", "failed"]
    log: str
    created_at: datetime
    completed_at: datetime | None
