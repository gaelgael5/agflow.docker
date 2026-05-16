from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class LocalBackupSummary(BaseModel):
    id: UUID
    filename: str
    size_bytes: int | None
    status: str
    created_at: datetime
    source_remote_connection_id: UUID | None = None
    source_kind: Literal["manual", "full", "snapshot"] = "manual"
