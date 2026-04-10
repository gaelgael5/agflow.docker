from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

Section = Literal["roles", "missions", "competences"]

_ALLOWED_SERVICE_TYPES = {
    "documentation",
    "code",
    "design",
    "automation",
    "task_list",
    "specs",
    "contract",
}


class RoleCreate(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    service_types: list[str] = Field(default_factory=list)
    identity_md: str = ""

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "id must be a slug: lowercase alphanumeric + _ and -"
            )
        return v

    @field_validator("service_types")
    @classmethod
    def _valid_services(cls, v: list[str]) -> list[str]:
        unknown = [s for s in v if s not in _ALLOWED_SERVICE_TYPES]
        if unknown:
            raise ValueError(f"Unknown service types: {unknown}")
        return v


class RoleUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    service_types: list[str] | None = None
    identity_md: str | None = None
    runtime_config: dict | None = None

    @field_validator("service_types")
    @classmethod
    def _valid_services(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        unknown = [s for s in v if s not in _ALLOWED_SERVICE_TYPES]
        if unknown:
            raise ValueError(f"Unknown service types: {unknown}")
        return v


class RoleSummary(BaseModel):
    id: str
    display_name: str
    description: str
    service_types: list[str]
    identity_md: str
    prompt_agent_md: str
    prompt_orchestrator_md: str
    runtime_config: dict
    created_at: datetime
    updated_at: datetime


class DocumentCreate(BaseModel):
    section: Section
    name: str = Field(min_length=1, max_length=200)
    content_md: str = ""
    protected: bool = False

    @field_validator("name")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must be non-empty")
        return v


class DocumentUpdate(BaseModel):
    content_md: str | None = None
    protected: bool | None = None


class DocumentSummary(BaseModel):
    id: UUID
    role_id: str
    section: Section
    parent_path: str
    name: str
    content_md: str
    protected: bool
    created_at: datetime
    updated_at: datetime


class RoleDetail(BaseModel):
    role: RoleSummary
    roles_documents: list[DocumentSummary]
    missions_documents: list[DocumentSummary]
    competences_documents: list[DocumentSummary]
