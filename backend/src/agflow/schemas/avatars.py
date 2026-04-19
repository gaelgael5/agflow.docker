from __future__ import annotations

from pydantic import BaseModel, Field


class ThemeCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    prompt: str = Field(min_length=1)
    provider: str = "dall-e-3"
    size: str = "1024x1024"
    quality: str = "hd"
    style: str = "vivid"


class ThemeUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    prompt: str | None = None
    provider: str | None = None
    size: str | None = None
    quality: str | None = None
    style: str | None = None


class ImageInfo(BaseModel):
    number: int
    filename: str
    size_bytes: int
    is_selected: bool


class CharacterSummary(BaseModel):
    slug: str
    display_name: str
    description: str
    image_count: int
    selected: int | None


class CharacterDetail(CharacterSummary):
    prompt: str
    images: list[ImageInfo]


class ThemeSummary(BaseModel):
    slug: str
    display_name: str
    description: str
    provider: str
    character_count: int
    image_count: int


class ThemeDetail(ThemeSummary):
    prompt: str
    size: str
    quality: str
    style: str
    characters: list[CharacterSummary]


class CharacterCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    prompt: str = Field(min_length=1)


class CharacterUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    prompt: str | None = None


class GenerateRequest(BaseModel):
    api_key: str | None = None
