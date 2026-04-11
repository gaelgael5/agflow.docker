from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

Section = str
NATIVE_SECTIONS: tuple[str, ...] = ("roles", "missions", "competences")
_SECTION_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def validate_section_slug(v: str) -> str:
    v = v.strip().lower()
    if not _SECTION_SLUG_RE.match(v):
        raise ValueError(
            "section name must be a slug: lowercase alphanumeric + _ and -, "
            "start with alphanumeric, max 64 chars"
        )
    return v


class RoleCreate(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    # Service types are validated at service layer against the service_types
    # DB table (see service_types_service.validate_names). Pydantic here
    # only enforces they are strings; admins can add/remove types from the
    # dedicated CRUD page.
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


class RoleUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    service_types: list[str] | None = None
    identity_md: str | None = None
    runtime_config: dict | None = None


class RoleSummary(BaseModel):
    id: str
    display_name: str
    description: str
    service_types: list[str]
    identity_md: str
    prompt_orchestrator_md: str
    runtime_config: dict
    created_at: datetime
    updated_at: datetime


class DocumentCreate(BaseModel):
    section: Section
    name: str = Field(min_length=1, max_length=200)
    content_md: str = ""
    protected: bool = False

    @field_validator("section")
    @classmethod
    def _valid_section(cls, v: str) -> str:
        return validate_section_slug(v)

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


class SectionSummary(BaseModel):
    name: str
    display_name: str
    is_native: bool
    position: int


class SectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return validate_section_slug(v)


class SectionWithDocuments(SectionSummary):
    documents: list[DocumentSummary]


class RoleDetail(BaseModel):
    role: RoleSummary
    sections: list[SectionWithDocuments]
