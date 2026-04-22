from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ── Script (fichier .sh en BDD) ──────────────────────────

class ScriptRow(BaseModel):
    id: UUID
    name: str
    description: str
    content: str
    execute_on_types_named: UUID | None = None
    execute_on_types_named_name: str | None = None
    created_at: datetime
    updated_at: datetime


class ScriptSummary(BaseModel):
    """Script without the full content (for listing)."""
    id: UUID
    name: str
    description: str
    execute_on_types_named: UUID | None = None
    execute_on_types_named_name: str | None = None
    created_at: datetime
    updated_at: datetime


class ScriptCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    content: str = ""
    execute_on_types_named: UUID | None = None


class ScriptUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    execute_on_types_named: UUID | None = None


# ── Group → Script reference ─────────────────────────────

Timing = Literal["before", "after"]


class GroupScriptRow(BaseModel):
    id: UUID
    group_id: UUID
    script_id: UUID
    script_name: str
    machine_id: UUID
    machine_name: str
    timing: Timing
    position: int
    env_mapping: dict[str, str]
    created_at: datetime
    updated_at: datetime


class GroupScriptCreate(BaseModel):
    script_id: UUID
    machine_id: UUID
    timing: Timing
    position: int = 0
    env_mapping: dict[str, str] = Field(default_factory=dict)


class GroupScriptUpdate(BaseModel):
    script_id: UUID | None = None
    machine_id: UUID | None = None
    timing: Timing | None = None
    position: int | None = None
    env_mapping: dict[str, str] | None = None
