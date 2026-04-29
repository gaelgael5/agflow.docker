"""DTOs for the public SaaS runtime API (`/api/v1/runtimes`)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class GroupSelectionEntry(BaseModel):
    replica_count: int = Field(ge=0)


class RuntimeCreate(BaseModel):
    """Body for `POST /api/v1/projects/{id}/runtimes`."""

    environment: str | None = None
    groups: dict[UUID, GroupSelectionEntry] = Field(default_factory=dict)
    user_secrets: dict[str, str] = Field(default_factory=dict)


class GroupRuntimeOut(BaseModel):
    id: UUID
    group_id: UUID
    group_name: str
    replica_count: int = 1
    machine_id: UUID | None = None
    status: str
    pushed_at: datetime | None = None
    error_message: str | None = None


class RuntimeOut(BaseModel):
    id: UUID
    seq: int
    project_id: UUID
    user_id: UUID | None = None
    status: str
    pushed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    group_runtimes: list[GroupRuntimeOut] = Field(default_factory=list)


class RuntimeEndpointPort(BaseModel):
    container: int
    host: int | None = None
    protocol: str = "tcp"


class RuntimeEndpoint(BaseModel):
    container_name: str
    image: str
    host: str
    ports: list[RuntimeEndpointPort] = Field(default_factory=list)
    status: str
    raw_status: str = ""


class ProjectGroupOut(BaseModel):
    id: UUID
    name: str
    max_replicas: int = 1
    instance_count: int = 0


class ProjectSummaryPublic(BaseModel):
    id: UUID
    display_name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    group_count: int = 0


class ProjectDetailPublic(ProjectSummaryPublic):
    groups: list[ProjectGroupOut] = Field(default_factory=list)


def parse_endpoints(rows: list[dict[str, Any]]) -> list[RuntimeEndpoint]:
    """Convert raw inspect rows from project_runtimes_service.inspect_endpoints
    into typed DTOs. Lenient on missing fields (Docker output varies)."""
    out: list[RuntimeEndpoint] = []
    for r in rows:
        ports = [
            RuntimeEndpointPort(
                container=int(p["container"]),
                host=int(p["host"]) if "host" in p else None,
                protocol=str(p.get("protocol", "tcp")),
            )
            for p in r.get("ports", [])
        ]
        out.append(
            RuntimeEndpoint(
                container_name=r.get("container_name", ""),
                image=r.get("image", ""),
                host=r.get("host", ""),
                ports=ports,
                status=r.get("status", "unknown"),
                raw_status=r.get("raw_status", ""),
            ),
        )
    return out
