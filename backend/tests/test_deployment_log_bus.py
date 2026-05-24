import asyncio
import pytest
from uuid import uuid4
from agflow.services.deployment_log_bus import DeploymentLogBus


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    bus = DeploymentLogBus()
    dep_id = uuid4()
    q = bus.subscribe(dep_id)

    await bus.publish(dep_id, {"type": "log", "line": "hello"})
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event == {"type": "log", "line": "hello"}


@pytest.mark.asyncio
async def test_close_puts_none_sentinel():
    bus = DeploymentLogBus()
    dep_id = uuid4()
    q = bus.subscribe(dep_id)

    await bus.close(dep_id)
    sentinel = await asyncio.wait_for(q.get(), timeout=1.0)
    assert sentinel is None


@pytest.mark.asyncio
async def test_publish_to_unknown_deployment_is_noop():
    bus = DeploymentLogBus()
    dep_id = uuid4()
    # Pas d'abonné — ne doit pas lever d'exception
    await bus.publish(dep_id, {"type": "log", "line": "ignored"})


@pytest.mark.asyncio
async def test_unsubscribe_removes_queue():
    bus = DeploymentLogBus()
    dep_id = uuid4()
    q = bus.subscribe(dep_id)
    bus.unsubscribe(dep_id, q)

    # After unsubscribe, publishing should be a noop (no queues left)
    await bus.publish(dep_id, {"type": "log", "line": "should not arrive"})

    # Queue should be empty (no event received)
    assert q.empty()


@pytest.mark.asyncio
async def test_close_is_idempotent():
    bus = DeploymentLogBus()
    dep_id = uuid4()
    q = bus.subscribe(dep_id)

    await bus.close(dep_id)
    await bus.close(dep_id)  # Should not raise or send extra None

    # Only one sentinel should be received
    sentinel = await asyncio.wait_for(q.get(), timeout=1.0)
    assert sentinel is None
    assert q.empty()  # No second None sent
