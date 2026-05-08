from __future__ import annotations

from pydantic import BaseModel, Field


class UserSecretSummary(BaseModel):
    name: str
    description: str | None = None


class UserSecretCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_\-]+$")
    value: str = Field(min_length=1)
    description: str | None = None


class UserSecretUpdate(BaseModel):
    value: str = Field(min_length=1)


class UserSecretReveal(BaseModel):
    name: str
    value: str
