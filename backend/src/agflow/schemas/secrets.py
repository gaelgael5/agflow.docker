from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

Scope = Literal["global", "agent"]


class SecretCreate(BaseModel):
    var_name: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1)
    scope: Scope = "global"

    @field_validator("var_name")
    @classmethod
    def _upper_snake_case(cls, v: str) -> str:
        v = v.strip()
        if not v.replace("_", "").isalnum():
            raise ValueError(
                "var_name must contain only alphanumeric characters and underscores"
            )
        return v.upper()


class SecretUpdate(BaseModel):
    value: str | None = Field(default=None, min_length=1)
    scope: Scope | None = None


class SecretSummary(BaseModel):
    id: UUID
    var_name: str
    scope: Scope
    created_at: datetime
    updated_at: datetime
    used_by: list[str] = Field(default_factory=list)


class SecretReveal(BaseModel):
    id: UUID
    var_name: str
    value: str


class SecretTestResult(BaseModel):
    supported: bool
    ok: bool
    detail: str
