"""DTOs Pydantic v2 conformes au contrat workflow v5
(cf. docs/contracts/docker-orchestration-flow.md).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Catalogue projets (#1, #2) ─────────────────────────────────────


class ResourceSummary(BaseModel):
    type: str
    label: str


class ProjectSummaryV5(BaseModel):
    project_id: UUID
    name: str
    description: str
    resources_summary: list[ResourceSummary]


class ResourceDetail(BaseModel):
    type: str
    label: str
    catalog_id: str


class ProjectDetailV5(BaseModel):
    project_id: UUID
    name: str
    description: str
    resources: list[ResourceDetail]


# ── Runtimes (#3, #4) ──────────────────────────────────────────────


class RuntimeProvisionResponse(BaseModel):
    runtime_id: UUID
    status: str = Field(description='Au moment du début : "provisioning"')


class ResourceState(BaseModel):
    resource_id: UUID = Field(description="UUID v4 stable par runtime")
    type: str
    name: str
    status: str = Field(description="provisioning | ready | failed | pending_setup")
    connection_params: dict[str, Any] | None = None
    mcp_bindings: list[dict[str, Any]] = Field(default_factory=list)
    setup_steps: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None


class RuntimeResourcesResponse(BaseModel):
    runtime_id: UUID
    status: str = Field(
        description=(
            "provisioning | ready | partially_ready | failed "
            "(mapping v5 §3.4 calculé depuis le status DB + statuts des resources)"
        )
    )
    resources: list[ResourceState]


# ── Sessions (#5, #6, #7, #8) ──────────────────────────────────────


class SessionCreateRequest(BaseModel):
    api_key_id: UUID
    name: str | None = None
    duration_seconds: int = Field(ge=60, le=86_400 * 30)
    project_runtime_id: UUID | None = None
    callback_url: str | None = None
    callback_hmac_key_id: str | None = Field(default=None, max_length=64)


class SessionCreateResponse(BaseModel):
    session_id: UUID
    expires_at: str


class AgentCreateRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    labels: dict[str, Any] = Field(default_factory=dict)
    mission: str | None = None
    count: int = Field(default=1, ge=1, le=10)


class AgentCreateResponse(BaseModel):
    agent_instance_ids: list[UUID]


class WorkRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agflow_correlation_id: UUID = Field(alias="_agflow_correlation_id")
    agflow_action_execution_id: UUID = Field(alias="_agflow_action_execution_id")
    instruction: dict[str, Any]


class WorkResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_id: UUID
    agflow_correlation_id: UUID = Field(alias="_agflow_correlation_id")
    agflow_action_execution_id: UUID = Field(alias="_agflow_action_execution_id")


# ── HMAC keys (#9) ─────────────────────────────────────────────────


class HmacKeyCreateRequest(BaseModel):
    key_id: str = Field(min_length=1, max_length=64)
    secret_hex: str = Field(min_length=32, max_length=128)
    description: str = ""


class HmacKeyCreateResponse(BaseModel):
    key_id: str
    description: str
    created_at: str


# ── Task status (#10) ──────────────────────────────────────────────


class TaskStatusResponse(BaseModel):
    """Shape conforme contrat v5 §3.7 + champs de corrélation pour ag.flow recovery."""

    task_id: UUID
    kind: str
    status: str = Field(description="pending | running | completed | failed | cancelled")
    session_id: UUID | None = None
    agent_instance_id: UUID | None = None
    agflow_correlation_id: UUID | None = None
    agflow_action_execution_id: UUID | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str
