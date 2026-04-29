from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ── Categories ───────────────────────────────────────────

class CategoryRow(BaseModel):
    name: str
    is_vps: bool = False


class CategoryActionRow(BaseModel):
    id: UUID
    name: str
    is_required: bool = False


# ── Named types (variantes typées, ex. Proxmox/SSH) ──────

class NamedTypeRow(BaseModel):
    id: UUID
    name: str
    type_id: str
    type_name: str
    sub_type_id: UUID | None
    sub_type_name: str | None
    connection_type: str
    created_at: datetime
    updated_at: datetime


class NamedTypeCreate(BaseModel):
    name: str = Field(min_length=1)
    type_id: str = Field(min_length=1)
    sub_type_id: UUID | None = None
    connection_type: str = Field(min_length=1)


class NamedTypeUpdate(BaseModel):
    name: str | None = None
    type_id: str | None = None
    sub_type_id: UUID | None = None
    connection_type: str | None = None


# ── Named type actions (URLs par action de catégorie) ────

class NamedTypeActionRow(BaseModel):
    id: UUID
    named_type_id: UUID
    category_action_id: UUID
    action_name: str
    url: str
    created_at: datetime
    updated_at: datetime


class NamedTypeActionCreate(BaseModel):
    category_action_id: UUID
    url: str = Field(min_length=1)


class NamedTypeActionUpdate(BaseModel):
    url: str | None = None


# ── Certificates ─────────────────────────────────────────

class CertificateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    private_key: str = Field(min_length=1)
    public_key: str | None = None
    passphrase: str | None = None


class CertificateUpdate(BaseModel):
    name: str | None = None
    private_key: str | None = None
    public_key: str | None = None
    passphrase: str | None = None


class CertificateGenerate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    key_type: str = "rsa"
    passphrase: str | None = None


class CertificateSummary(BaseModel):
    id: UUID
    name: str
    key_type: str = "rsa"
    has_private_key: bool = True
    has_public_key: bool = False
    has_passphrase: bool = False
    created_at: datetime
    updated_at: datetime


# ── Machines (ex-servers + ex-machines fusionnées) ───────

class MachineCreate(BaseModel):
    name: str = ""
    type_id: UUID
    host: str = Field(min_length=1)
    port: int = 22
    username: str | None = None
    password: str | None = None
    certificate_id: UUID | None = None
    parent_id: UUID | None = None
    user_id: UUID | None = None
    environment: str | None = None


class MachineUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    certificate_id: UUID | None = None
    user_id: UUID | None = None
    environment: str | None = None


class RequiredActionStatus(BaseModel):
    name: str
    done: bool


class MachineSummary(BaseModel):
    id: UUID
    name: str = ""
    type_id: UUID
    type_name: str
    category: str
    host: str
    port: int
    username: str | None
    has_password: bool = False
    certificate_id: UUID | None
    parent_id: UUID | None = None
    user_id: UUID | None = None
    environment: str | None = None
    children_count: int = 0
    metadata: dict[str, str] = {}
    status: str = "not_initialized"
    required_actions: list[RequiredActionStatus] = []
    created_at: datetime
    updated_at: datetime


# ── Machine runs (historique d'exécution de scripts) ─────

class MachineRunRow(BaseModel):
    id: UUID
    machine_id: UUID
    action_id: UUID
    action_name: str
    started_at: datetime
    finished_at: datetime | None
    success: bool | None
    exit_code: int | None
    error_message: str | None


# ── Script Execution ─────────────────────────────────────

class ScriptRunRequest(BaseModel):
    script_url: str = Field(min_length=1)
    args: dict[str, str] = Field(default_factory=dict)
