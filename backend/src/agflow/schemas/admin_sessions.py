from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AdminSessionListItem(BaseModel):
    id: UUID
    name: str | None
    status: str
    project_id: str | None
    created_at: datetime
    expires_at: datetime
    closed_at: datetime | None
    api_key_id: UUID
    agent_count: int
