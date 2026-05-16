"""Tests du reaper des oauth_pending_session expirés/consumed."""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

os.environ["HARPOCRATE_DEK"] = "test-dek-passphrase-very-long-and-stable-2026"

from agflow.db.pool import execute, fetch_one
from agflow.services.oauth_pending_reaper import purge_oauth_pending
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture
async def fresh_db():
    await reset_schema_and_migrate()
    yield


async def _insert_pending(*, state: str, expires_at: datetime, consumed_at: datetime | None = None) -> None:
    dek = os.environ["HARPOCRATE_DEK"]
    await execute(
        """
        INSERT INTO oauth_pending_session
            (state, kind, redirect_uri, form_data,
             client_secret_encrypted, expires_at, consumed_at)
        VALUES ($1, 'gdrive', 'r', '{}'::jsonb, PGP_SYM_ENCRYPT('s', $4), $2, $3)
        """,
        state, expires_at, consumed_at, dek,
    )


@pytest.mark.asyncio
async def test_purge_removes_expired_rows(fresh_db) -> None:
    now = datetime.now(UTC)
    await _insert_pending(state="expired", expires_at=now - timedelta(hours=2))
    await _insert_pending(state="fresh", expires_at=now + timedelta(minutes=5))

    purged = await purge_oauth_pending()
    assert purged >= 1

    assert await fetch_one("SELECT 1 FROM oauth_pending_session WHERE state = $1", "expired") is None
    assert await fetch_one("SELECT 1 FROM oauth_pending_session WHERE state = $1", "fresh") is not None


@pytest.mark.asyncio
async def test_purge_removes_consumed_rows(fresh_db) -> None:
    now = datetime.now(UTC)
    await _insert_pending(
        state="consumed", expires_at=now + timedelta(minutes=5),
        consumed_at=now,
    )

    purged = await purge_oauth_pending()
    assert purged >= 1
    assert await fetch_one("SELECT 1 FROM oauth_pending_session WHERE state = $1", "consumed") is None
