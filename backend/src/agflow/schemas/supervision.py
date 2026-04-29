from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class SessionStatusCounts(BaseModel):
    active: int
    closed: int
    expired: int


class AgentStatusCounts(BaseModel):
    idle: int
    busy: int
    error: int
    destroyed_total: int


class MomDeliveryCounts(BaseModel):
    pending: int
    claimed: int
    failed: int


class SupervisionOverview(BaseModel):
    sessions: SessionStatusCounts
    agents: AgentStatusCounts
    containers_running: int | None
    mom: MomDeliveryCounts


class SupervisedInstance(BaseModel):
    id: UUID
    session_id: UUID
    agent_id: str
    mission: str | None
    status: str
    last_activity_at: datetime
    created_at: datetime
    destroyed_at: datetime | None
    error_message: str | None
    last_container_name: str | None


class InstanceDetail(BaseModel):
    id: UUID
    session_id: UUID
    agent_id: str
    labels: dict[str, Any]
    mission: str | None
    status: str
    last_activity_at: datetime
    created_at: datetime
    destroyed_at: datetime | None
    error_message: str | None
    last_container_name: str | None
    container_status: str | None
    mom_counts: MomDeliveryCounts
    recent_messages: list[dict[str, Any]]
