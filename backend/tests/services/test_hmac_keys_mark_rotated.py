"""Tests de hmac_keys_service.mark_rotated (soft-delete)."""
from __future__ import annotations

import os

import pytest

# Fernet (via _fernet()) nécessite HARPOCRATE_DEK pour chiffrer/déchiffrer.
os.environ.setdefault("HARPOCRATE_DEK", "test-dek-passphrase-very-long-and-stable-2026")

pytestmark = pytest.mark.asyncio


async def test_mark_rotated_sets_rotated_at(fresh_db):
    from agflow.services import hmac_keys_service

    key_id = "test-rotate-1"
    await hmac_keys_service.create(
        key_id=key_id, secret_hex="0123456789abcdef" * 4, description=""
    )
    await hmac_keys_service.mark_rotated(key_id=key_id)

    row = await fresh_db.fetchrow(
        "SELECT rotated_at FROM hmac_keys WHERE key_id = $1", key_id
    )
    assert row is not None
    assert row["rotated_at"] is not None


async def test_mark_rotated_idempotent(fresh_db):
    """Appeler 2x mark_rotated n'ecrase pas la 1ere date (preserve l'historique)."""
    from agflow.services import hmac_keys_service

    key_id = "test-rotate-idem"
    await hmac_keys_service.create(
        key_id=key_id, secret_hex="0123456789abcdef" * 4, description=""
    )
    await hmac_keys_service.mark_rotated(key_id=key_id)
    first_row = await fresh_db.fetchrow(
        "SELECT rotated_at FROM hmac_keys WHERE key_id = $1", key_id
    )
    first_ts = first_row["rotated_at"]

    await hmac_keys_service.mark_rotated(key_id=key_id)
    second_row = await fresh_db.fetchrow(
        "SELECT rotated_at FROM hmac_keys WHERE key_id = $1", key_id
    )
    assert second_row["rotated_at"] == first_ts  # inchangé


async def test_mark_rotated_unknown_raises(fresh_db):
    from agflow.services import hmac_keys_service

    with pytest.raises(hmac_keys_service.HmacKeyNotFoundError):
        await hmac_keys_service.mark_rotated(key_id="nonexistent")
