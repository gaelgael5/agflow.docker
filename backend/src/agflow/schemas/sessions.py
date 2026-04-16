from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

DEFAULT_SESSION_DURATION_S = 3600
MAX_SESSION_DURATION_S = 86400

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _validate_slug(v: str) -> str:
    if not _SLUG_RE.match(v):
        raise ValueError(
            f"slug must match {_SLUG_RE.pattern}, got '{v}'"
        )
    return v


class SessionCreate(BaseModel):
    name: str | None = None
    duration_seconds: int = Field(
        default=DEFAULT_SESSION_DURATION_S, ge=60, le=MAX_SESSION_DURATION_S,
    )


class SessionExtend(BaseModel):
    duration_seconds: int = Field(ge=60, le=MAX_SESSION_DURATION_S)


class SessionOut(BaseModel):
    id: UUID
    name: str | None
    status: str
    created_at: datetime
    expires_at: datetime
    closed_at: datetime | None
    api_key_id: UUID


class AgentInstanceCreate(BaseModel):
    agent_id: str
    count: int = Field(default=1, ge=1, le=50)
    labels: dict[str, Any] = Field(default_factory=dict)
    mission: str | None = None

    @field_validator("agent_id")
    @classmethod
    def _check_slug(cls, v: str) -> str:
        return _validate_slug(v)


class AgentInstanceOut(BaseModel):
    id: UUID
    session_id: UUID
    agent_id: str
    labels: dict[str, Any]
    mission: str | None
    status: str
    created_at: datetime


class AgentInstanceCreated(BaseModel):
    instance_ids: list[UUID]
