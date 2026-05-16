"""Schemas Pydantic pour les planifications de backups (full cron + snapshot interval)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Full schedules (cron) ───────────────────────────────────────────────


class FullScheduleSummary(BaseModel):
    """Représentation publique d'un schedule full."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    cron_expr: str
    remote_connection_id: UUID | None
    retention_count: int
    enabled: bool
    last_run_at: datetime | None
    last_run_status: Literal["ok", "failed"] | None
    last_run_error: str | None
    created_at: datetime
    updated_at: datetime


class FullScheduleCreate(BaseModel):
    """Payload pour créer un schedule full."""

    name: str = Field(min_length=1, max_length=128)
    cron_expr: str = Field(min_length=1, max_length=128)
    remote_connection_id: UUID | None = None
    retention_count: int = Field(default=10, ge=1)
    enabled: bool = True


class FullScheduleUpdate(BaseModel):
    """Payload pour mettre à jour un schedule full. Tous les champs optionnels."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    cron_expr: str | None = Field(default=None, min_length=1, max_length=128)
    remote_connection_id: UUID | None = None
    retention_count: int | None = Field(default=None, ge=1)
    enabled: bool | None = None


# ── Snapshot schedules (interval) ──────────────────────────────────────


class SnapshotScheduleSummary(BaseModel):
    """Représentation publique d'un schedule snapshot."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    interval_amount: int
    interval_unit: Literal["minutes", "hours"]
    remote_connection_id: UUID | None
    retention_count: int
    enabled: bool
    last_run_at: datetime | None
    last_run_status: Literal["ok", "failed"] | None
    last_run_error: str | None
    created_at: datetime
    updated_at: datetime


class SnapshotScheduleCreate(BaseModel):
    """Payload pour créer un schedule snapshot."""

    name: str = Field(min_length=1, max_length=128)
    interval_amount: int = Field(ge=1)
    interval_unit: Literal["minutes", "hours"]
    remote_connection_id: UUID | None = None
    retention_count: int = Field(default=24, ge=1)
    enabled: bool = True


class SnapshotScheduleUpdate(BaseModel):
    """Payload pour mettre à jour un schedule snapshot. Tous les champs optionnels."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    interval_amount: int | None = Field(default=None, ge=1)
    interval_unit: Literal["minutes", "hours"] | None = None
    remote_connection_id: UUID | None = None
    retention_count: int | None = Field(default=None, ge=1)
    enabled: bool | None = None
