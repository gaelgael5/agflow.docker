from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

Transport = Literal["stdio", "sse", "docker", "streamable-http"]


class DiscoveryServiceCreate(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1)
    api_key_var: str | None = None
    description: str = ""
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "id must be a slug: lowercase alphanumeric + _ and -"
            )
        return v


class DiscoveryServiceUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key_var: str | None = None
    description: str | None = None
    enabled: bool | None = None


class DiscoveryServiceSummary(BaseModel):
    id: str
    name: str
    base_url: str
    api_key_var: str | None
    description: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ProbeResult(BaseModel):
    ok: bool
    detail: str


class MCPSearchItem(BaseModel):
    package_id: str
    name: str
    repo: str = ""
    repo_url: str = ""
    transport: Transport = "stdio"
    short_description: str = ""
    long_description: str = ""
    documentation_url: str = ""


class MCPInstallPayload(BaseModel):
    discovery_service_id: str
    package_id: str


class MCPServerSummary(BaseModel):
    id: UUID
    discovery_service_id: str
    package_id: str
    name: str
    repo: str
    repo_url: str
    transport: Transport
    short_description: str
    long_description: str
    documentation_url: str
    parameters: dict
    parameters_schema: list
    created_at: datetime
    updated_at: datetime


class MCPParametersUpdate(BaseModel):
    parameters: dict


class SkillSearchItem(BaseModel):
    skill_id: str
    name: str
    description: str = ""


class SkillInstallPayload(BaseModel):
    discovery_service_id: str
    skill_id: str


class SkillSummary(BaseModel):
    id: UUID
    discovery_service_id: str
    skill_id: str
    name: str
    description: str
    content_md: str
    created_at: datetime
    updated_at: datetime
