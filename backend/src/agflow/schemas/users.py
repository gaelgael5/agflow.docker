from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    name: str = Field(default="", max_length=200)
    role: Literal["admin", "user"] = "user"
    scopes: list[str] = Field(default_factory=list)
    status: Literal["pending", "active"] = "active"


class UserSummary(BaseModel):
    id: UUID
    email: str
    name: str
    avatar_url: str
    role: str
    scopes: list[str]
    status: str
    created_at: datetime
    approved_at: datetime | None
    last_login: datetime | None
    api_key_count: int = 0


class UserUpdate(BaseModel):
    name: str | None = None
    role: Literal["admin", "user"] | None = None
    scopes: list[str] | None = None
