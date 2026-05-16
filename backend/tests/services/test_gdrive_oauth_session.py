"""Tests intégration de gdrive_oauth_session (DB + vault mockés)."""
from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

# Force HARPOCRATE_DEK pour les opérations PGP_SYM_*
os.environ["HARPOCRATE_DEK"] = "test-dek-passphrase-very-long-and-stable-2026"

from agflow.db.pool import fetch_one
from agflow.services import gdrive_oauth_session
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture
async def fresh_db():
    await reset_schema_and_migrate()
    yield


async def _create_admin_user() -> uuid.UUID:
    from agflow.db.pool import execute
    user_id = uuid.uuid4()
    await execute(
        "INSERT INTO users (id, email, name, role, status) "
        "VALUES ($1, $2, 'admin', 'admin', 'active')",
        user_id, f"admin-{user_id}@example.com",
    )
    return user_id


@pytest.mark.asyncio
async def test_start_session_creates_pending_row_and_returns_url(fresh_db) -> None:
    actor = await _create_admin_user()

    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/auth?state=abc",
        "abc",
    )

    with patch(
        "agflow.services.gdrive_oauth_session.gdrive_client.build_flow",
        return_value=fake_flow,
    ):
        state, url = await gdrive_oauth_session.start_session(
            actor_user_id=actor,
            name="My Drive Backups",
            folder_name="agflow-backups",
            client_id="abc.apps.googleusercontent.com",
            client_secret="GOCSPX-secret",
            redirect_uri="https://example.com/cb",
        )

    assert len(state) >= 32
    assert "accounts.google.com" in url

    row = await fetch_one(
        "SELECT kind, redirect_uri, form_data, consumed_at, "
        "PGP_SYM_DECRYPT(client_secret_encrypted, $2) AS secret "
        "FROM oauth_pending_session WHERE state = $1",
        state, os.environ["HARPOCRATE_DEK"],
    )
    assert row is not None
    assert row["kind"] == "gdrive"
    assert row["redirect_uri"] == "https://example.com/cb"
    assert row["consumed_at"] is None
    assert row["secret"] == "GOCSPX-secret"

    import json
    fd = row["form_data"]
    if isinstance(fd, str):
        fd = json.loads(fd)
    assert fd["name"] == "My Drive Backups"
    assert fd["folder_name"] == "agflow-backups"
    assert fd["client_id"] == "abc.apps.googleusercontent.com"
    # Le secret ne doit JAMAIS apparaître dans form_data
    assert "client_secret" not in fd
