from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ── Categories ───────────────────────────────────────────

class CategoryRow(BaseModel):
    name: str
    visible_in_machines: bool = False


class CategoryActionRow(BaseModel):
    id: UUID
    name: str
    is_required: bool = False
    creates_category: str | None = None


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
    creates_named_type_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class NamedTypeActionCreate(BaseModel):
    category_action_id: UUID
    url: str = Field(min_length=1)
    creates_named_type_id: UUID | None = None


class NamedTypeActionUpdate(BaseModel):
    url: str | None = None
    creates_named_type_id: UUID | None = None


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


# ── Swarm clusters (B0) ──────────────────────────────────────────────────


class SwarmClusterRow(BaseModel):
    """Public representation of a Swarm cluster. Tokens NEVER exposed."""

    id: UUID
    name: str
    manager_addr: str
    node_count: int = 0
    manager_count: int = 0
    worker_count: int = 0
    created_at: datetime
    updated_at: datetime


class SwarmInitRequest(BaseModel):
    cluster_name: str = Field(..., min_length=1, max_length=64)


class SwarmJoinRequest(BaseModel):
    cluster_id: UUID
    role: str = Field(..., pattern="^(manager|worker)$")


class SwarmLeaveRequest(BaseModel):
    force: bool = False


# ── Ingestion JSON depuis create-swarm-lxc.sh ────────────────────────────


class _Identification(BaseModel):
    ctid: int
    hostname: str
    hostname_raw: str | None = None


class _Systeme(BaseModel):
    distro: str
    ip: str
    ip_type: str = Field(..., pattern="^(static|dhcp)$")


class _UserBlock(BaseModel):
    user: str
    password: str | None = None
    ssh_key_private_path: str | None = None
    ssh_key_public_path: str | None = None
    ssh_key_public: str | None = None
    groups: list[str] = []
    sudo_nopasswd: bool = False


class _DockerBlock(BaseModel):
    docker_ok: bool
    docker_version: str | None = None
    compose_version: str | None = None
    hello_world_ok: bool | None = None


class _SwarmBlock(BaseModel):
    swarm_mode: str
    swarm_ready: bool
    tun_device_present: bool | None = None


class _HostBlock(BaseModel):
    proxmox_host: str | None = None
    created_at: str | None = None
    script_version: str | None = None
    conf_path: str | None = None
    conf_backup_path: str | None = None


class CreateLxcOutput(BaseModel):
    """JSON contract returned by create-swarm-lxc.sh (Configurations repo).

    Le champ identification.ctid correspond a la colonne DB lxc_ctid (renommee
    pour eviter le conflit avec la colonne systeme Postgres `ctid`).
    """

    status: str = Field(..., pattern="^(ok|partial)$")
    exit_code: int
    identification: _Identification
    ressources: dict | None = None
    systeme: _Systeme
    ssh_root: dict | None = None
    users: list[_UserBlock]
    docker: _DockerBlock
    swarm: _SwarmBlock
    host: _HostBlock | None = None
