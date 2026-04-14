from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

NetworkMode = Literal["bridge", "host", "none"]
ImageStatus = Literal["missing", "stale", "fresh"]

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class AgentMCPBinding(BaseModel):
    mcp_server_id: UUID
    parameters_override: dict = Field(default_factory=dict)
    position: int = 0


class AgentSkillBinding(BaseModel):
    skill_id: UUID
    position: int = 0


class _AgentBase(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    dockerfile_id: str = Field(min_length=1)
    role_id: str = Field(min_length=1)
    env_vars: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=3600, gt=0)
    workspace_path: str = "/workspace"
    network_mode: NetworkMode = "bridge"
    graceful_shutdown_secs: int = Field(default=30, ge=0)
    force_kill_delay_secs: int = Field(default=10, ge=0)
    mcp_bindings: list[AgentMCPBinding] = Field(default_factory=list)
    skill_bindings: list[AgentSkillBinding] = Field(default_factory=list)


class AgentCreate(_AgentBase):
    slug: str = Field(min_length=1, max_length=64)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG_RE.match(v):
            raise ValueError(
                "slug must be lowercase alphanumeric + dashes, "
                "start with alphanumeric, max 64 chars"
            )
        return v


class AgentUpdate(_AgentBase):
    pass


class AgentSummary(BaseModel):
    id: UUID
    slug: str
    display_name: str
    description: str
    dockerfile_id: str
    role_id: str
    env_vars: dict[str, Any]
    timeout_seconds: int
    workspace_path: str
    network_mode: NetworkMode
    graceful_shutdown_secs: int
    force_kill_delay_secs: int
    is_assistant: bool = False
    created_at: datetime
    updated_at: datetime
    has_errors: bool = False


class AgentProfileSummary(BaseModel):
    id: UUID
    agent_id: UUID
    name: str
    description: str
    document_ids: list[UUID]
    created_at: datetime
    updated_at: datetime


class AgentProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    document_ids: list[UUID] = Field(default_factory=list)


class AgentProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    document_ids: list[UUID] | None = None


class AgentDetail(AgentSummary):
    mcp_bindings: list[AgentMCPBinding]
    skill_bindings: list[AgentSkillBinding]
    image_status: ImageStatus


class DuplicatePayload(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG_RE.match(v):
            raise ValueError("slug must be lowercase alphanumeric + dashes")
        return v


class SkillPreview(BaseModel):
    skill_id: UUID
    name: str
    content_md: str


class ConfigPreview(BaseModel):
    prompt_md: str
    mcp_json: dict
    tools_json: list[dict]
    env_file: str
    skills: list[SkillPreview]
    validation_errors: list[str]
    image_status: ImageStatus
    # Name of the profile applied to this preview, if any. None means the
    # agent was previewed in its default (identity-only) state.
    profile_name: str | None = None
    # UUIDs referenced by the applied profile that no longer exist in
    # role_documents — empty when profile_id is None or all refs are valid.
    broken_document_ids: list[UUID] = Field(default_factory=list)
