from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ── Types ────────────────────────────────────────────────

InfraType = Literal["platform", "service"]


class TypeRow(BaseModel):
    name: str
    category: InfraType = Field(alias="type")

    model_config = {"populate_by_name": True}


# ── Platforms (from disk) ────────────────────────────────

class ScriptArg(BaseModel):
    arg: str
    label_fr: str = ""
    description_fr: str = ""
    type: str = "string"
    required: bool = True


class ScriptManifest(BaseModel):
    args: list[ScriptArg] = Field(default_factory=list)
    command: str = ""


class PlatformDef(BaseModel):
    name: str
    type: str = ""
    service: str
    connection: str = "SSH"
    scripts: dict[str, list[str]] = Field(default_factory=dict)


class ServiceDef(BaseModel):
    name: str
    type: str = ""
    connection: str = "SSH"
    scripts: list[str] = Field(default_factory=list)


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


# ── Servers ──────────────────────────────────────────────

class ServerCreate(BaseModel):
    name: str = ""
    type: str = Field(min_length=1)
    host: str = Field(min_length=1)
    port: int = 22
    username: str | None = None
    password: str | None = None
    certificate_id: UUID | None = None


class ServerUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    certificate_id: UUID | None = None


class ServerSummary(BaseModel):
    id: UUID
    name: str = ""
    type: str
    host: str
    port: int
    username: str | None
    has_password: bool = False
    certificate_id: UUID | None
    parent_id: UUID | None = None
    machine_count: int = 0
    metadata: dict[str, str] = {}
    status: str = "not_initialized"
    created_at: datetime
    updated_at: datetime


# ── Machines ─────────────────────────────────────────────

InstallStatus = Literal["pending", "initializing", "installed", "failed"]


class MachineCreate(BaseModel):
    host: str = Field(min_length=1)
    port: int = 22
    type: str = Field(min_length=1)
    server_id: UUID | None = None
    username: str | None = None
    password: str | None = None
    certificate_id: UUID | None = None


class MachineUpdate(BaseModel):
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    certificate_id: UUID | None = None


class MachineSummary(BaseModel):
    id: UUID
    host: str
    port: int
    type: str
    server_id: UUID | None
    username: str | None
    has_password: bool = False
    certificate_id: UUID | None
    install_status: InstallStatus
    install_step: int
    install_total: int | None
    created_at: datetime
    updated_at: datetime


# ── Machine Metadata ─────────────────────────────────────

class MetadataItem(BaseModel):
    key: str
    value: str
    is_sensitive: bool


class MetadataUpsert(BaseModel):
    value: str
    is_sensitive: bool | None = None


# ── Script Execution ─────────────────────────────────────

class ScriptRunRequest(BaseModel):
    script_url: str = Field(min_length=1)
    args: dict[str, str] = Field(default_factory=dict)
