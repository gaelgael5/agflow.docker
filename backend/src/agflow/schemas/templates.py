from __future__ import annotations

from pydantic import BaseModel, Field


class TemplateCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""


class TemplateUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None


class TemplateSummary(BaseModel):
    slug: str
    display_name: str
    description: str
    cultures: list[str]


class TemplateFileInfo(BaseModel):
    filename: str
    culture: str
    size: int


class TemplateDetail(BaseModel):
    slug: str
    display_name: str
    description: str
    files: list[TemplateFileInfo]


class FileCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    content: str = ""


class FileUpdate(BaseModel):
    content: str
