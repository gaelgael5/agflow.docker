from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ── Image Registries ─────────────────────────────────────

AuthType = Literal["none", "basic", "token"]


class RegistryCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1)
    auth_type: AuthType = "none"
    credential_ref: str | None = None


class RegistryUpdate(BaseModel):
    display_name: str | None = None
    url: str | None = None
    auth_type: AuthType | None = None
    credential_ref: str | None = None


class RegistrySummary(BaseModel):
    id: str
    display_name: str
    url: str
    auth_type: AuthType
    credential_ref: str | None = None
    is_default: bool = False


# ── Product Catalog ──────────────────────────────────────

Category = Literal["wiki", "tasks", "code", "design", "infra", "other"]


class ProductSummary(BaseModel):
    id: str
    display_name: str
    description: str
    category: Category
    tags: list[str] = Field(default_factory=list)
    min_ram_mb: int = 512
    config_only: bool = False
    has_openapi: bool = False
    mcp_package_id: str | None = None
    recipe_version: str = "1.0.0"


class ProductCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: Category = "other"
    tags: list[str] = Field(default_factory=list)
    recipe_yaml: str = ""


class ProductDetail(ProductSummary):
    recipe: dict[str, Any] = Field(default_factory=dict)
    recipe_yaml: str = ""


# ── Projects ─────────────────────────────────────────────

Environment = Literal["dev", "staging", "prod"]


class ProjectCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    environment: Environment = "dev"
    tags: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    environment: Environment | None = None
    tags: list[str] | None = None


class ProjectSummary(BaseModel):
    id: str
    display_name: str
    description: str
    environment: Environment
    tags: list[str] = Field(default_factory=list)


# ── Product Instances ────────────────────────────────────

InstanceStatus = Literal["draft", "active", "stopped"]


class InstanceCreate(BaseModel):
    instance_name: str = Field(min_length=1, max_length=128)
    catalog_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    variables: dict[str, str] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    service_role: str | None = None


class InstanceUpdate(BaseModel):
    variables: dict[str, str] | None = None
    secret_refs: dict[str, str] | None = None
    service_role: str | None = None
    service_url: str | None = None


class InstanceSummary(BaseModel):
    id: str
    instance_name: str
    catalog_id: str
    project_id: str
    variables: dict[str, str] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    service_role: str | None = None
    status: InstanceStatus = "draft"
    service_url: str | None = None
