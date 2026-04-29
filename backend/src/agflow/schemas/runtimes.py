from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

RuntimeStatus = Literal["pending", "deployed", "failed"]


class ProjectGroupRuntimeRow(BaseModel):
    id: UUID
    seq: int
    project_runtime_id: UUID
    group_id: UUID
    group_name: str = ""
    machine_id: UUID | None
    machine_name: str = ""
    remote_path: str = ""
    status: RuntimeStatus
    pushed_at: datetime | None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectGroupRuntimeDetail(ProjectGroupRuntimeRow):
    env_text: str = ""
    compose_yaml: str = ""


class ProjectRuntimeRow(BaseModel):
    id: UUID
    seq: int
    project_id: UUID
    deployment_id: UUID | None
    user_id: UUID | None
    user_email: str | None = None
    status: RuntimeStatus
    pushed_at: datetime | None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    group_runtimes: list[ProjectGroupRuntimeRow] = []
