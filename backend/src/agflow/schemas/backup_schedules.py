"""Schemas Pydantic pour les planifications de backups (full cron)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Full schedules (cron) ───────────────────────────────────────────────


class FullScheduleSummary(BaseModel):
    """Représentation publique d'un schedule full (multi-remote)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    cron_expr: str
    remote_connection_ids: list[UUID]
    keep_local: bool
    retention_count: int
    enabled: bool
    last_run_at: datetime | None
    last_run_status: Literal["ok", "failed"] | None
    last_run_error: str | None
    created_at: datetime
    updated_at: datetime


class CreateFullPayload(BaseModel):
    """Payload pour créer un schedule full."""

    name: str
    cron_expr: str
    remote_connection_ids: list[UUID] = []
    keep_local: bool = True
    retention_count: int = 10
    enabled: bool = True


# Alias backward-compat (service + tests existants)
FullScheduleCreate = CreateFullPayload


class UpdateFullPayload(BaseModel):
    """Payload pour mettre à jour un schedule full. Tous les champs optionnels."""

    name: str | None = None
    cron_expr: str | None = None
    remote_connection_ids: list[UUID] | None = None
    keep_local: bool | None = None
    retention_count: int | None = Field(default=None, ge=1)
    enabled: bool | None = None


# Alias backward-compat (service + tests existants)
FullScheduleUpdate = UpdateFullPayload


# ── History ────────────────────────────────────────────────────────────


class ScheduleHistoryEntry(BaseModel):
    """One backup row attached to a schedule — for the history view."""

    id: UUID
    filename: str
    file_path: str
    size_bytes: int | None
    status: str  # 'in_progress' | 'completed' | 'failed'
    created_at: datetime
    created_by_user_id: UUID | None
