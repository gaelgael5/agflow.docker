"""Tests du worker hook_dispatcher (POST hooks signés HMAC vers ag.flow)."""
from __future__ import annotations

import pytest
import respx
from httpx import Response

pytestmark = pytest.mark.asyncio


async def test_dispatcher_posts_signed_hook_marks_delivered(
    fresh_db, mock_pending_hook
):
    from agflow.workers import hook_dispatcher_worker

    hook_id = mock_pending_hook["hook_id"]
    url = mock_pending_hook["callback_url"]

    with respx.mock(assert_all_called=True) as router:
        route = router.post(url).mock(return_value=Response(200))
        await hook_dispatcher_worker.process_batch()

    assert route.called
    req = route.calls[0].request
    assert "X-Agflow-Hook-Id" in req.headers
    assert req.headers["X-Agflow-Hook-Id"] == str(hook_id)
    assert "X-Agflow-Timestamp" in req.headers
    assert "X-Agflow-Signature" in req.headers
    assert req.headers["X-Agflow-Signature"].startswith("hmac-sha256=")

    row = await fresh_db.fetchrow(
        "SELECT status, last_response_code FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    assert row["status"] == "delivered"
    assert row["last_response_code"] == 200


async def test_dispatcher_5xx_schedules_retry(fresh_db, mock_pending_hook):
    from agflow.workers import hook_dispatcher_worker

    hook_id = mock_pending_hook["hook_id"]
    url = mock_pending_hook["callback_url"]

    with respx.mock():
        respx.post(url).mock(return_value=Response(500))
        await hook_dispatcher_worker.process_batch()

    row = await fresh_db.fetchrow(
        "SELECT status, attempt_number FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    assert row["status"] == "pending"
    assert row["attempt_number"] == 1


async def test_dispatcher_401_marks_dead_non_retryable(
    fresh_db, mock_pending_hook
):
    from agflow.workers import hook_dispatcher_worker

    hook_id = mock_pending_hook["hook_id"]
    url = mock_pending_hook["callback_url"]

    with respx.mock():
        respx.post(url).mock(return_value=Response(401))
        await hook_dispatcher_worker.process_batch()

    row = await fresh_db.fetchrow(
        "SELECT status FROM outbound_hooks WHERE hook_id = $1", hook_id
    )
    assert row["status"] == "dead"


async def test_dispatcher_timeout_schedules_retry(fresh_db, mock_pending_hook):
    import httpx

    from agflow.workers import hook_dispatcher_worker

    hook_id = mock_pending_hook["hook_id"]
    url = mock_pending_hook["callback_url"]

    with respx.mock():
        respx.post(url).mock(side_effect=httpx.TimeoutException("timeout"))
        await hook_dispatcher_worker.process_batch()

    row = await fresh_db.fetchrow(
        "SELECT status, attempt_number FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    assert row["status"] == "pending"
    assert row["attempt_number"] == 1


async def test_dispatcher_skips_future_next_retry_at(
    fresh_db, mock_pending_hook
):
    from agflow.workers import hook_dispatcher_worker

    hook_id = mock_pending_hook["hook_id"]
    # Déplace next_retry_at dans le futur
    await fresh_db.execute(
        "UPDATE outbound_hooks SET next_retry_at = now() + interval '1 hour' WHERE hook_id = $1",
        hook_id,
    )

    with respx.mock(assert_all_called=False) as router:
        route = router.post(mock_pending_hook["callback_url"]).mock(
            return_value=Response(200)
        )
        await hook_dispatcher_worker.process_batch()
        assert not route.called


async def test_dispatcher_max_attempts_marks_dead(fresh_db, mock_pending_hook):
    """Après attempt_number = 6 (= MAX_ATTEMPTS) + nouveau retry 5xx → dead."""
    from agflow.workers import hook_dispatcher_worker

    hook_id = mock_pending_hook["hook_id"]
    url = mock_pending_hook["callback_url"]

    # Simuler 6 attempts déjà faits
    await fresh_db.execute(
        "UPDATE outbound_hooks SET attempt_number = 6 WHERE hook_id = $1",
        hook_id,
    )

    with respx.mock():
        respx.post(url).mock(return_value=Response(503))
        await hook_dispatcher_worker.process_batch()

    row = await fresh_db.fetchrow(
        "SELECT status FROM outbound_hooks WHERE hook_id = $1", hook_id
    )
    assert row["status"] == "dead"
