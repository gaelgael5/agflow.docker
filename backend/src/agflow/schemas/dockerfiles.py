from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

BuildStatus = Literal["pending", "running", "success", "failed"]
DisplayStatus = Literal["never_built", "up_to_date", "outdated", "failed", "building"]


class DockerfileCreate(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    parameters: dict = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "id must be a slug: lowercase alphanumeric + _ and -"
            )
        return v


class DockerfileUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    parameters: dict | None = None


class DockerfileSummary(BaseModel):
    id: str
    display_name: str
    description: str
    parameters: dict
    current_hash: str
    display_status: DisplayStatus
    latest_build_id: UUID | None
    created_at: datetime
    updated_at: datetime


def _validate_file_path(v: str) -> str:
    v = v.strip().replace("\\", "/")
    if not v:
        raise ValueError("path cannot be empty")
    if v.startswith("/"):
        raise ValueError("path must be relative")
    parts = v.split("/")
    for part in parts:
        if not part or part in (".", ".."):
            raise ValueError("path contains invalid segment")
    return v


class FileCreate(BaseModel):
    path: str = Field(min_length=1, max_length=200)
    content: str = ""

    @field_validator("path")
    @classmethod
    def _clean_path(cls, v: str) -> str:
        return _validate_file_path(v)


class FileCreateBase64(BaseModel):
    """FileCreate where content is base64-encoded."""

    path: str = Field(min_length=1, max_length=200)
    content: str = ""
    encoding: str = "base64"

    @field_validator("path")
    @classmethod
    def _clean_path(cls, v: str) -> str:
        return _validate_file_path(v)


class FileUpdate(BaseModel):
    content: str | None = None


class FileUpdateBase64(BaseModel):
    """FileUpdate where content is base64-encoded."""

    content: str | None = None
    encoding: str = "base64"


class FileSummary(BaseModel):
    id: UUID
    dockerfile_id: str
    path: str
    content: str
    encoding: str = "utf-8"
    created_at: datetime
    updated_at: datetime


class FileSummaryBase64(BaseModel):
    """Same as FileSummary but content is base64-encoded (for API responses)."""

    id: UUID
    dockerfile_id: str
    path: str
    content: str
    encoding: str = "base64"
    created_at: datetime
    updated_at: datetime


class DockerfileDetail(BaseModel):
    dockerfile: DockerfileSummary
    files: list[FileSummary]


class BuildSummary(BaseModel):
    id: UUID
    dockerfile_id: str
    content_hash: str
    image_tag: str
    status: BuildStatus
    logs: str
    started_at: datetime
    finished_at: datetime | None
