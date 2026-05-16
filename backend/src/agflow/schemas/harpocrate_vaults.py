"""Schemas pour les coffres Harpocrate configurables côté DB.

Le mot de passe API (`api_key`) n'apparaît jamais dans les réponses publiques.
Pour le set ou le rotate, le client envoie un `VaultCreateRequest` ou
`VaultUpdateRequest` ; le service chiffre via pgcrypto puis stocke en bytea.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class VaultSummary(BaseModel):
    """Représentation publique d'un coffre — pas d'API key exposée."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    base_url: str
    api_key_id: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class VaultCreateRequest(BaseModel):
    """Payload pour créer un nouveau coffre."""

    name: str = Field(min_length=1, max_length=128)
    base_url: HttpUrl
    api_key_id: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1)
    is_default: bool = False


class VaultUpdateRequest(BaseModel):
    """Payload pour mettre à jour un coffre. Tous les champs sont optionnels.

    `api_key` n'est mis à jour que s'il est fourni (rotation du token).
    `is_default` à `True` déplace le flag default vers ce coffre (atomique).
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: HttpUrl | None = None
    api_key_id: str | None = Field(default=None, min_length=1, max_length=128)
    api_key: str | None = Field(default=None, min_length=1)
    is_default: bool | None = None


class VaultTestConnectionResult(BaseModel):
    """Réponse de `POST /api/admin/harpocrate-vaults/{id}/test-connection`."""

    ok: bool
    error: str | None = None
