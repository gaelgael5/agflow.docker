# backend/src/agflow/schemas/local_backup_pushes.py
"""DTO pour l'historique des pushes (1 backup x N remotes)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class LocalBackupPushSummary(BaseModel):
    id: UUID
    local_backup_id: UUID
    remote_connection_id: UUID
    remote_connection_name: str
    status: Literal["pending", "pushing", "ok", "failed"]
    pushed_at: datetime | None
    error: str | None
    remote_path: str | None
    size_bytes: int | None
    created_at: datetime
    updated_at: datetime
