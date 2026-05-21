"""Pydantic schemas for `group_variables` — variables globales de groupe.

Cf. migration 119 + service `group_variables_service`.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class GroupVariableRow(BaseModel):
    id: UUID
    group_id: UUID
    name: str
    value: str
    description: str = ""
    created_at: datetime
    updated_at: datetime


class GroupVariableCreate(BaseModel):
    """Création / upsert d'une variable globale au niveau d'un groupe.

    `name` doit respecter la convention shell `[A-Za-z_][A-Za-z0-9_]*` —
    validé applicativement dans le service (la DB est laxiste pour permettre
    des alias non-conformes si jamais).

    `value` peut être :
        - une valeur littérale (ex: `"outline.yoops.org"`)
        - une référence déclarative `${vault://api1:path}` ou `${env://NAME}`
          (résolue au Generate via platform_secrets_service).
    """
    name: str = Field(min_length=1, max_length=128)
    value: str = ""
    description: str = ""


class GroupVariableUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    value: str | None = None
    description: str | None = None
