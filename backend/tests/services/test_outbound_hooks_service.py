"""Tests de outbound_hooks_service."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


async def test_enqueue_creates_pending_row(fresh_db, mock_hmac_key):
    from agflow.services import outbound_hooks_service as oh

    hook_id = uuid4()
    await oh.enqueue(
        hook_id=hook_id,
        task_id=uuid4(),
        callback_url="https://ag.flow/hooks",
        hmac_key_id=mock_hmac_key,
        payload={"status": "completed"},
    )
    row = await fresh_db.fetchrow(
        "SELECT status, attempt_number FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    assert row["status"] == "pending"
    assert row["attempt_number"] == 0


async def test_claim_pending_returns_due_hooks(fresh_db, mock_hmac_key):
    from agflow.services import outbound_hooks_service as oh

    hook_id_a = uuid4()
    hook_id_b = uuid4()
    await oh.enqueue(
        hook_id=hook_id_a,
        task_id=None,
        callback_url="https://a",
        hmac_key_id=mock_hmac_key,
        payload={},
    )
    # B avec next_retry_at dans le futur → ne doit pas être claimé.
    await fresh_db.execute(
        """
        INSERT INTO outbound_hooks (hook_id, callback_url, hmac_key_id, payload,
            next_retry_at, status)
        VALUES ($1, 'https://b', $2, '{}'::jsonb, now() + interval '1 hour', 'pending')
        """,
        hook_id_b,
        mock_hmac_key,
    )

    claimed = await oh.claim_pending(limit=10)
    claimed_hook_ids = {row["hook_id"] for row in claimed}
    assert hook_id_a in claimed_hook_ids
    assert hook_id_b not in claimed_hook_ids


async def test_mark_delivered_sets_status_delivered(fresh_db, mock_hmac_key):
    from agflow.services import outbound_hooks_service as oh

    hook_id = uuid4()
    await oh.enqueue(
        hook_id=hook_id, task_id=None, callback_url="https://x",
        hmac_key_id=mock_hmac_key, payload={},
    )
    await oh.mark_delivered(hook_id=hook_id, response_code=200)
    row = await fresh_db.fetchrow(
        "SELECT status, last_response_code FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    assert row["status"] == "delivered"
    assert row["last_response_code"] == 200


async def test_schedule_retry_calculates_backoff(fresh_db, mock_hmac_key):
    from agflow.services import outbound_hooks_service as oh

    hook_id = uuid4()
    await oh.enqueue(
        hook_id=hook_id, task_id=None, callback_url="https://x",
        hmac_key_id=mock_hmac_key, payload={},
    )
    before = datetime.now(UTC)
    await oh.schedule_retry(
        hook_id=hook_id, response_code=500, error_message="server error"
    )
    row = await fresh_db.fetchrow(
        """
        SELECT status, attempt_number, next_retry_at, last_response_code, error_message
        FROM outbound_hooks WHERE hook_id = $1
        """,
        hook_id,
    )
    assert row["status"] == "pending"
    assert row["attempt_number"] == 1
    # 1er retry = 1s plus tard
    assert row["next_retry_at"] - before >= timedelta(seconds=1)
    assert row["next_retry_at"] - before < timedelta(seconds=3)
    assert row["last_response_code"] == 500


async def test_schedule_retry_after_max_attempts_marks_dead(
    fresh_db, mock_hmac_key
):
    from agflow.services import outbound_hooks_service as oh

    hook_id = uuid4()
    # Insère directement avec attempt_number à un cran sous la limite (5)
    await fresh_db.execute(
        """
        INSERT INTO outbound_hooks (hook_id, callback_url, hmac_key_id, payload,
            status, attempt_number, next_retry_at)
        VALUES ($1, 'https://x', $2, '{}'::jsonb, 'pending', 6, now())
        """,
        hook_id,
        mock_hmac_key,
    )
    # 7e tentative = > MAX_ATTEMPTS (6) → mark_dead
    await oh.schedule_retry(
        hook_id=hook_id, response_code=500, error_message="exhausted"
    )
    row = await fresh_db.fetchrow(
        "SELECT status FROM outbound_hooks WHERE hook_id = $1", hook_id
    )
    assert row["status"] == "dead"


async def test_mark_dead_sets_status_dead(fresh_db, mock_hmac_key):
    from agflow.services import outbound_hooks_service as oh

    hook_id = uuid4()
    await oh.enqueue(
        hook_id=hook_id, task_id=None, callback_url="https://x",
        hmac_key_id=mock_hmac_key, payload={},
    )
    await oh.mark_dead(hook_id=hook_id, error_message="non-retryable 401")
    row = await fresh_db.fetchrow(
        "SELECT status, error_message FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    assert row["status"] == "dead"
    assert "non-retryable" in row["error_message"]
