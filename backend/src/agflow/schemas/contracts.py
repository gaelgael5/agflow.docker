from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ContractCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    source_type: Literal["upload", "url", "manual"] = "manual"
    source_url: str | None = None
    spec_content: str = Field(min_length=1)
    base_url: str = ""
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer"
    auth_secret_ref: str | None = None
    tag_overrides: dict[str, str] = Field(default_factory=dict)
    output_dir: str = "workspace/docs/ctr"


class ContractUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    source_url: str | None = None
    spec_content: str | None = None
    base_url: str | None = None
    auth_header: str | None = None
    auth_prefix: str | None = None
    auth_secret_ref: str | None = None
    tag_overrides: dict[str, str] | None = None
    output_dir: str | None = None


class TagSummary(BaseModel):
    slug: str
    name: str
    description: str
    resolved_description: str = ""
    operation_count: int


class ContractSummary(BaseModel):
    id: UUID
    agent_id: str
    slug: str
    display_name: str
    description: str
    source_type: str
    source_url: str | None
    base_url: str
    auth_header: str
    auth_prefix: str
    auth_secret_ref: str | None
    parsed_tags: list[TagSummary]
    tag_overrides: dict[str, str] = Field(default_factory=dict)
    managed_by_instance: UUID | None = None
    output_dir: str = "workspace/docs/ctr"
    position: int
    created_at: datetime
    updated_at: datetime


class ContractDetail(ContractSummary):
    spec_content: str
