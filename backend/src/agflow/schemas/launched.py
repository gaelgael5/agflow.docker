from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class LaunchedTaskSummary(BaseModel):
    id: UUID
    dockerfile_id: str
    container_name: str | None
    instruction: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    exit_code: int | None
