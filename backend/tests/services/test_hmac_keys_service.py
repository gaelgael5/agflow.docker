"""Tests de hmac_keys_service."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from asyncpg import Connection

from agflow.db.pool import get_pool
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def test_create_inserts_and_encrypts(fresh_db: Connection):
    from agflow.services import hmac_keys_service

    secret = "0123456789abcdef" * 4  # 64 hex
    await hmac_keys_service.create(
        key_id="test-key-1",
        secret_hex=secret,
        description="test key",
    )
    row = await fresh_db.fetchrow(
        "SELECT key_id, key_value_encrypted, description FROM hmac_keys WHERE key_id = $1",
        "test-key-1",
    )
    assert row is not None
    assert row["description"] == "test key"
    # encrypted blob != cleartext
    assert bytes(row["key_value_encrypted"]) != secret.encode()


async def test_create_duplicate_raises(fresh_db: Connection):
    from agflow.services import hmac_keys_service

    secret = "0123456789abcdef" * 4
    await hmac_keys_service.create(key_id="dup-key", secret_hex=secret, description="")
    with pytest.raises(hmac_keys_service.DuplicateHmacKeyError):
        await hmac_keys_service.create(
            key_id="dup-key", secret_hex=secret, description=""
        )


async def test_get_by_key_id_returns_decrypted(fresh_db: Connection):
    from agflow.services import hmac_keys_service

    secret = "0123456789abcdef" * 4
    await hmac_keys_service.create(
        key_id="readback", secret_hex=secret, description=""
    )
    got = await hmac_keys_service.get_by_key_id("readback")
    assert got is not None
    assert got["secret_hex"] == secret
    assert got["key_id"] == "readback"
