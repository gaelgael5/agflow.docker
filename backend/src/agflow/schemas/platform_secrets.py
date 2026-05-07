from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class PlatformSecretSummary(BaseModel):
    id: UUID
    key: str
    type: Literal["vault", "env"]
    name: str
    has_value: bool
    created_at: datetime
    updated_at: datetime


class PlatformSecretReveal(BaseModel):
    id: UUID
    name: str
    value: str


class PlatformSecretCreateVault(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v.replace("_", "").isalnum():
            raise ValueError("Le nom ne peut contenir que des lettres, chiffres et underscores")
        return v.upper()


class PlatformSecretCreateEnv(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    value: str = Field(default="")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v.replace("_", "").isalnum():
            raise ValueError("Le nom ne peut contenir que des lettres, chiffres et underscores")
        return v.upper()


class PlatformSecretUpdate(BaseModel):
    value: str
