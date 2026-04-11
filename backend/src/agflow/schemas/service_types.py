from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ServiceTypeSummary(BaseModel):
    name: str
    display_name: str
    is_native: bool
    position: int
    created_at: datetime


class ServiceTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        v = v.strip().lower()
        if not _NAME_RE.match(v):
            raise ValueError(
                "name must be a slug: lowercase alphanumeric + _ and -"
            )
        return v
