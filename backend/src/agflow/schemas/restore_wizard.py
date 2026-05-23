"""Schémas Pydantic pour le wizard de restauration en 4 étapes.

Flux : connexion vault → sélection connexion distante → navigation fichiers → restauration.
Les credentials vault sont transmis inline à chaque requête (pas de session persistée).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class VaultRef(BaseModel):
    """Credentials d'accès au vault Harpocrate (URL + API key)."""

    url: str = Field(min_length=1, max_length=2048)
    api_key: str = Field(min_length=1, max_length=1024)


class VaultSecretsRequest(VaultRef):
    """Body pour lister les secrets vault filtrés par préfixe."""

    path: str = ""


class VaultSecretItem(BaseModel):
    name: str
    tags: list[str]


class RemoteBrowseRequest(BaseModel):
    """Requête de navigation dans un répertoire distant."""

    connection_type: Literal["sftp", "s3", "ftps", "gdrive"]
    manual_fields: dict[str, str]
    vault_mappings: dict[str, str]  # field_name → vault secret name
    vault: VaultRef
    path: str = Field(default="/", min_length=1, max_length=4096)


class RemoteEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None
    modified_at: datetime | None


class RestoreExecuteRequest(BaseModel):
    """Requête de restauration : télécharge le fichier distant et l'injecte dans Postgres."""

    connection_type: Literal["sftp", "s3", "ftps", "gdrive"]
    manual_fields: dict[str, str]
    vault_mappings: dict[str, str]
    vault: VaultRef
    file_path: str  # chemin complet du fichier sur le remote


class RestoreJobStarted(BaseModel):
    job_id: UUID


class RestoreJobStatus(BaseModel):
    job_id: UUID
    status: Literal["running", "done", "failed"]
    log: str
    created_at: datetime
    completed_at: datetime | None
