from __future__ import annotations

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, execute, fetch_one, get_pool
from agflow.mom.consumer import MomConsumer
from agflow.mom.envelope import Direction, Kind
from agflow.mom.publisher import MomPublisher
from agflow.workers.mom_reclaimer import reclaim_once


@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    yield p
    await close_pool()


@pytest.mark.asyncio
async def test_reclaim_once_returns_counts_per_group(pool) -> None:
    counts = await reclaim_once()
    assert set(counts.keys()) == {"dispatcher", "router", "ws_push"}
    for v in counts.values():
        assert v >= 0


@pytest.mark.asyncio
async def test_reclaim_once_reclaims_stale_dispatcher_message(pool) -> None:
    publisher = MomPublisher(
        pool=pool,
        groups_config={Direction.IN: ["dispatcher"], Direction.OUT: []},
    )
    consumer = MomConsumer(
        pool=pool,
        group_name="dispatcher",
        consumer_id="reclaim-test",
    )
    msg_id = await publisher.publish(
        session_id="s-reclaim",
        instance_id="i-reclaim",
        direction=Direction.IN,
        source="test",
        kind=Kind.INSTRUCTION,
        payload={"text": "stale"},
    )
    claimed = await consumer.claim_batch(
        instance_id="i-reclaim",
        direction=Direction.IN,
        batch_size=10,
    )
    assert len(claimed) == 1

    # Rendre la claim stale (vieille de 5 min)
    await execute(
        "UPDATE agent_message_delivery "
        "SET claimed_at = now() - interval '5 minutes' "
        "WHERE msg_id = $1 AND group_name = 'dispatcher'",
        msg_id,
    )

    counts = await reclaim_once()
    assert counts["dispatcher"] >= 1

    row = await fetch_one(
        "SELECT status FROM agent_message_delivery WHERE group_name = 'dispatcher' AND msg_id = $1",
        msg_id,
    )
    assert row["status"] == "pending"
