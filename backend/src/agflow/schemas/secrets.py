from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SecretSummary(BaseModel):
    name: str
    is_placeholder: bool = False
    description: str | None = None
    tags: list[str] = []


class SecretCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def _upper_snake_case(cls, v: str) -> str:
        v = v.strip()
        if not v.replace("_", "").isalnum():
            raise ValueError(
                "name must contain only alphanumeric characters and underscores"
            )
        return v.upper()


class SecretUpdate(BaseModel):
    value: str = Field(min_length=1)


class SecretReveal(BaseModel):
    name: str
    value: str


class SecretTestResult(BaseModel):
    supported: bool
    ok: bool
    detail: str
