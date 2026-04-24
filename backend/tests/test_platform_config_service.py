from __future__ import annotations

import pytest

from agflow.db.pool import execute
from agflow.services import platform_config_service

pytestmark = pytest.mark.asyncio


async def _cleanup(key: str) -> None:
    await execute("DELETE FROM platform_config WHERE key = $1", key)


async def test_get_returns_none_when_missing() -> None:
    await _cleanup("test.missing")
    assert await platform_config_service.get("test.missing") is None


async def test_get_int_returns_default_when_missing() -> None:
    await _cleanup("test.missing_int")
    assert await platform_config_service.get_int("test.missing_int", default=42) == 42


async def test_set_and_get_value() -> None:
    await _cleanup("test.roundtrip")
    await platform_config_service.set_value("test.roundtrip", "hello")
    assert await platform_config_service.get("test.roundtrip") == "hello"
    await _cleanup("test.roundtrip")


async def test_set_value_upserts() -> None:
    await _cleanup("test.upsert")
    await platform_config_service.set_value("test.upsert", "v1")
    await platform_config_service.set_value("test.upsert", "v2")
    assert await platform_config_service.get("test.upsert") == "v2"
    await _cleanup("test.upsert")


async def test_get_int_parses_value() -> None:
    await _cleanup("test.parse_int")
    await platform_config_service.set_value("test.parse_int", "123")
    assert await platform_config_service.get_int("test.parse_int", default=0) == 123
    await _cleanup("test.parse_int")


async def test_get_int_falls_back_on_invalid_value() -> None:
    await _cleanup("test.bad_int")
    await platform_config_service.set_value("test.bad_int", "not-a-number")
    assert await platform_config_service.get_int("test.bad_int", default=99) == 99
    await _cleanup("test.bad_int")


async def test_default_supervision_timeouts_are_seeded() -> None:
    value = await platform_config_service.get("agent_idle_timeout_s")
    assert value == "600"
    value = await platform_config_service.get("session_idle_timeout_s")
    assert value == "120"
    value = await platform_config_service.get("supervision_reaper_interval_s")
    assert value == "20"
    value = await platform_config_service.get("supervision_reclaim_interval_s")
    assert value == "15"
    value = await platform_config_service.get("supervision_reclaim_stale_threshold_s")
    assert value == "30"
