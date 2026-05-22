# backend/src/agflow/schemas/infra_env_vars.py
"""Pydantic schemas pour infra_named_type_env_vars + infra_machine_env_vars.

Cf. migration 121 + service infra_env_vars_service.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

_NAME_RE = r"^[A-Za-z_][A-Za-z0-9_]*$"


class NamedTypeEnvVarRow(BaseModel):
    id: UUID
    named_type_id: UUID
    name: str
    description: str = ""
    position: int = 0
    is_secret: bool = False
    created_at: datetime
    updated_at: datetime


class NamedTypeEnvVarCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=_NAME_RE)
    description: str = ""
    position: int = 0
    is_secret: bool = False


class NamedTypeEnvVarUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128, pattern=_NAME_RE)
    description: str | None = None
    position: int | None = None
    is_secret: bool | None = None


class MachineEnvVarRow(BaseModel):
    """Vue dénormalisée : inclut name + description + is_secret issus du contrat."""
    id: UUID
    machine_id: UUID
    named_type_env_var_id: UUID
    name: str
    description: str
    value: str
    is_secret: bool = False
    created_at: datetime
    updated_at: datetime


class MachineSecretEntry(BaseModel):
    """Valeur secrète à stocker dans Harpocrate pour une variable de machine."""
    vault_name: str
    value: str


class MachineEnvVarUpsert(BaseModel):
    """Upsert atomique — valeurs plain + secrets à stocker dans le coffre."""
    values: dict[UUID, str] = Field(default_factory=dict)
    secrets: dict[UUID, MachineSecretEntry] = Field(default_factory=dict)


class ProjectEnvVarsCheckMissing(BaseModel):
    group_script_id: UUID
    script_id: UUID
    script_name: str
    group_id: UUID
    group_name: str
    machine_id: UUID | None
    machine_name: str | None
    target_kind: str
    missing_env_vars: list[str]


class ProjectEnvVarsCheck(BaseModel):
    project_id: UUID
    total_missing: int
    items: list[ProjectEnvVarsCheckMissing]
