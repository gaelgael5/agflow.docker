from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ServiceType = Literal["image_generation", "embedding", "llm"]


class ProviderConfig(BaseModel):
    service_type: ServiceType
    provider_name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    secret_ref: str = ""
    enabled: bool = True
    is_default: bool = False


class ProviderConfigUpdate(BaseModel):
    display_name: str | None = None
    secret_ref: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None


class ProviderSummary(BaseModel):
    service_type: ServiceType
    provider_name: str
    display_name: str
    secret_ref: str
    enabled: bool
    is_default: bool
