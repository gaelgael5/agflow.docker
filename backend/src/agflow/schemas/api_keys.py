from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[str] = Field(default_factory=list)
    rate_limit: int = Field(default=120, ge=1, le=10000)
    expires_in: Literal["3m", "6m", "9m", "12m", "never"] = "12m"


class ApiKeyCreated(BaseModel):
    id: UUID
    name: str
    prefix: str
    full_key: str
    scopes: list[str]
    rate_limit: int
    expires_at: datetime | None
    created_at: datetime


class ApiKeySummary(BaseModel):
    id: UUID
    owner_id: UUID | None
    name: str
    prefix: str
    scopes: list[str]
    rate_limit: int
    expires_at: datetime | None
    revoked: bool
    created_at: datetime
    last_used_at: datetime | None


class ApiKeyUpdate(BaseModel):
    name: str | None = None
    scopes: list[str] | None = None
    rate_limit: int | None = Field(default=None, ge=1, le=10000)
