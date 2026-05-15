from __future__ import annotations

import json
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)


async def create_anomaly(
    *,
    severity: str,
    anomaly_type: str,
    source: str,
    source_ref_id: UUID | None = None,
    message: str,
    metadata: dict | None = None,
) -> None:
    """Crée une anomalie système. Hystérésis : skip si une non-ack existe déjà."""
    existing = await fetch_one(
        "SELECT id FROM system_anomaly_events "
        "WHERE source = $1 AND source_ref_id IS NOT DISTINCT FROM $2 "
        "AND severity = $3 AND acknowledged_at IS NULL",
        source, source_ref_id, severity,
    )
    if existing:
        _log.debug("system_anomaly.skip_duplicate", source=source, severity=severity)
        return

    await execute(
        "INSERT INTO system_anomaly_events "
        "(severity, anomaly_type, source, source_ref_id, message, metadata) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        severity, anomaly_type, source, source_ref_id,
        message, json.dumps(metadata or {}),
    )
    _log.warning("system_anomaly.created", source=source, severity=severity, message=message)


async def list_unacknowledged() -> list[dict]:
    return await fetch_all(
        "SELECT id, detected_at, severity, anomaly_type, source, source_ref_id, message, metadata "
        "FROM system_anomaly_events WHERE acknowledged_at IS NULL ORDER BY detected_at DESC"
    )


async def acknowledge(anomaly_id: int, by_user_id: UUID) -> None:
    await execute(
        "UPDATE system_anomaly_events SET acknowledged_at=NOW(), acknowledged_by_user_id=$1 WHERE id=$2",
        by_user_id, anomaly_id,
    )
