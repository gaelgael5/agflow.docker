from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, execute, fetch_one, get_pool
from agflow.mom.consumer import MomConsumer
from agflow.mom.envelope import Direction, Kind
from agflow.mom.publisher import MomPublisher


@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    yield p
    await close_pool()


@pytest_asyncio.fixture
async def publisher(pool) -> MomPublisher:
    return MomPublisher(
        pool=pool,
        groups_config={Direction.IN: ["test_group"], Direction.OUT: ["test_group"]},
    )


@pytest_asyncio.fixture
async def consumer(pool) -> MomConsumer:
    return MomConsumer(pool=pool, group_name="test_group", consumer_id="test-worker-1")


@pytest.mark.asyncio
class TestMomConsumer:
    async def test_claim_and_ack(
        self, publisher: MomPublisher, consumer: MomConsumer,
    ) -> None:
        msg_id = await publisher.publish(
            session_id="s", instance_id="i", direction=Direction.IN,
            source="test", kind=Kind.INSTRUCTION, payload={"text": "go"},
        )
        claimed = await consumer.claim_batch(
            instance_id="i", direction=Direction.IN, batch_size=10,
        )
        assert len(claimed) == 1
        assert str(claimed[0].msg_id) == str(msg_id)
        assert claimed[0].kind == Kind.INSTRUCTION

        await consumer.ack(msg_id)
        row = await fetch_one(
            "SELECT status FROM agent_message_delivery "
            "WHERE group_name=$1 AND msg_id=$2",
            "test_group", msg_id,
        )
        assert row["status"] == "acked"

    async def test_skip_locked_prevents_double_claim(
        self, publisher: MomPublisher, pool,
    ) -> None:
        consumer_a = MomConsumer(pool=pool, group_name="test_group", consumer_id="A")
        consumer_b = MomConsumer(pool=pool, group_name="test_group", consumer_id="B")

        await publisher.publish(
            session_id="s", instance_id="i2", direction=Direction.IN,
            source="test", kind=Kind.INSTRUCTION, payload={"text": "only once"},
        )

        claimed_a = await consumer_a.claim_batch(
            instance_id="i2", direction=Direction.IN, batch_size=10,
        )
        claimed_b = await consumer_b.claim_batch(
            instance_id="i2", direction=Direction.IN, batch_size=10,
        )

        all_claimed = [*claimed_a, *claimed_b]
        assert len(all_claimed) == 1

    async def test_reclaim_stale(
        self, publisher: MomPublisher, consumer: MomConsumer,
    ) -> None:
        msg_id = await publisher.publish(
            session_id="s", instance_id="i3", direction=Direction.IN,
            source="test", kind=Kind.INSTRUCTION, payload={"text": "stale"},
        )
        await consumer.claim_batch(
            instance_id="i3", direction=Direction.IN, batch_size=10,
        )
        await execute(
            "UPDATE agent_message_delivery "
            "SET claimed_at = now() - interval '5 minutes' "
            "WHERE msg_id = $1 AND group_name = $2",
            msg_id, "test_group",
        )
        reclaimed = await consumer.reclaim_stale(max_idle=timedelta(seconds=30))
        assert reclaimed >= 1

        re_claimed = await consumer.claim_batch(
            instance_id="i3", direction=Direction.IN, batch_size=10,
        )
        assert len(re_claimed) == 1

    async def test_fail_increments_retry(
        self, publisher: MomPublisher, consumer: MomConsumer,
    ) -> None:
        msg_id = await publisher.publish(
            session_id="s", instance_id="i4", direction=Direction.IN,
            source="test", kind=Kind.INSTRUCTION, payload={"text": "fail me"},
        )
        await consumer.claim_batch(
            instance_id="i4", direction=Direction.IN, batch_size=10,
        )

        await consumer.fail(msg_id, error="test error")

        row = await fetch_one(
            "SELECT status, retry_count, last_error "
            "FROM agent_message_delivery "
            "WHERE group_name=$1 AND msg_id=$2",
            "test_group", msg_id,
        )
        assert row["retry_count"] == 1
        assert row["last_error"] == "test error"
        assert row["status"] == "pending"
