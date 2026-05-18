"""CRUD de outbound_hooks (queue des hooks à émettre vers ag.flow).

Conforme docs/contracts/hook-docker-task-completed.md §2 :
- Retry exponentiel : 1s, 5s, 30s, 2min, 10min, 1h → 6 tentatives max
- Au-delà → status='dead'
- Si 5xx → schedule_retry
- Si 4xx (sauf 408/429) → mark_dead (non-retryable)
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)

# Backoff plan : attempt_number → delay (s). attempt_number==1 = 1ère retry.
_BACKOFF_DELAYS_S = (1, 5, 30, 120, 600, 3600)
MAX_ATTEMPTS = len(_BACKOFF_DELAYS_S)


async def enqueue(
    *,
    hook_id: UUID,
    task_id: UUID | None,
    callback_url: str,
    hmac_key_id: str,
    payload: dict[str, Any],
) -> None:
    """INSERT row pending, next_retry_at=now() (claim immédiat possible)."""
    await execute(
        """
        INSERT INTO outbound_hooks
        (hook_id, task_id, callback_url, hmac_key_id, payload, status,
         attempt_number, next_retry_at)
        VALUES ($1, $2, $3, $4, $5::jsonb, 'pending', 0, now())
        """,
        hook_id,
        task_id,
        callback_url,
        hmac_key_id,
        json.dumps(payload),
    )
    _log.info(
        "workflow.hook.enqueued",
        hook_id=str(hook_id),
        task_id=str(task_id) if task_id else None,
        callback_url=callback_url,
    )


async def claim_pending(*, limit: int = 10) -> list[dict]:
    """SELECT pending hooks WHERE next_retry_at <= now(), ordered by created_at.

    Pas de FOR UPDATE ici car le dispatcher tourne sur 1 process unique en V1 ;
    si plusieurs dispatchers concurrents → ajouter SKIP LOCKED + transaction.
    """
    rows = await fetch_all(
        """
        SELECT hook_id, task_id, callback_url, hmac_key_id, payload,
               attempt_number
        FROM outbound_hooks
        WHERE status = 'pending' AND next_retry_at <= now()
        ORDER BY created_at
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def mark_delivered(*, hook_id: UUID, response_code: int) -> None:
    await execute(
        """
        UPDATE outbound_hooks
        SET status = 'delivered',
            last_response_code = $2,
            last_attempt_at = now(),
            error_message = NULL
        WHERE hook_id = $1
        """,
        hook_id,
        response_code,
    )
    _log.info(
        "workflow.hook.delivered",
        hook_id=str(hook_id),
        response_code=response_code,
    )


async def schedule_retry(
    *, hook_id: UUID, response_code: int | None, error_message: str
) -> None:
    """Incrémente attempt_number, calcule next_retry_at via backoff.

    Si attempt_number == MAX_ATTEMPTS → mark_dead à la place.
    """
    row = await fetch_one(
        "SELECT attempt_number FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    if row is None:
        return  # déjà nettoyée

    next_attempt = row["attempt_number"] + 1
    if next_attempt > MAX_ATTEMPTS:
        await mark_dead(hook_id=hook_id, error_message=f"max_attempts ({error_message})")
        return

    delay_s = _BACKOFF_DELAYS_S[next_attempt - 1]
    await execute(
        """
        UPDATE outbound_hooks
        SET attempt_number = $2,
            next_retry_at = now() + ($3 || ' seconds')::interval,
            last_response_code = $4,
            last_attempt_at = now(),
            error_message = $5
        WHERE hook_id = $1
        """,
        hook_id,
        next_attempt,
        str(delay_s),
        response_code,
        error_message,
    )
    _log.info(
        "workflow.hook.retry_scheduled",
        hook_id=str(hook_id),
        attempt=next_attempt,
        delay_s=delay_s,
        response_code=response_code,
    )


async def mark_dead(*, hook_id: UUID, error_message: str) -> None:
    await execute(
        """
        UPDATE outbound_hooks
        SET status = 'dead',
            error_message = $2,
            last_attempt_at = now()
        WHERE hook_id = $1
        """,
        hook_id,
        error_message,
    )
    _log.error(
        "workflow.hook.dead",
        hook_id=str(hook_id),
        error=error_message,
    )
