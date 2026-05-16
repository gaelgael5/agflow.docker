"""Tests intégration de gdrive_oauth_session (DB + vault mockés)."""
from __future__ import annotations

import json
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


async def _create_default_vault() -> None:
    """Seed un coffre Harpocrate default pour que _require_default_vault_name() trouve."""
    from agflow.db.pool import execute
    dek = os.environ["HARPOCRATE_DEK"]
    await execute(
        """
        INSERT INTO harpocrate_vaults
            (name, base_url, api_key_encrypted, is_default)
        VALUES ('default', 'https://vault.example.com', PGP_SYM_ENCRYPT('fake-key', $1), true)
        """,
        dek,
    )


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


@pytest.mark.asyncio
async def test_consume_session_happy_path_creates_connection_and_pushes_vault(
    fresh_db, vault_mock,
) -> None:
    actor = await _create_admin_user()
    await _create_default_vault()

    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://x", "x")
    fake_flow.credentials = MagicMock(
        refresh_token="1//refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="abc.apps.googleusercontent.com",
        client_secret="GOCSPX-secret",
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )

    fake_drive = MagicMock()
    # search-or-create: 0 résultat → on crée folder direct
    fake_drive.files().list().execute.return_value = {"files": []}
    fake_drive.files().create().execute.return_value = {"id": "folder-XYZ"}

    with (
        patch(
            "agflow.services.gdrive_oauth_session.gdrive_client.build_flow",
            return_value=fake_flow,
        ),
        patch(
            "agflow.services.gdrive_oauth_session.gdrive_client.build_drive_service",
            return_value=fake_drive,
        ),
        patch(
            "agflow.services.gdrive_oauth_session.gdrive_client.fetch_user_email",
            return_value="ops@example.com",
        ),
    ):
        # 1. start_session pour créer la pending row
        state, _url = await gdrive_oauth_session.start_session(
            actor_user_id=actor,
            name="Backups",
            folder_name="agflow-backups",
            client_id="abc.apps.googleusercontent.com",
            client_secret="GOCSPX-secret",
            redirect_uri="https://example.com/cb",
        )
        # 2. consume_session avec le code Google
        result = await gdrive_oauth_session.consume_session(
            state=state, code="auth-code-from-google",
        )

    assert "connection_id" in result
    assert result["user_email"] == "ops@example.com"
    assert result["folder_id"] == "folder-XYZ"

    # Connexion en DB
    conn = await fetch_one(
        "SELECT kind, name, config FROM remote_backup_connections WHERE id = $1",
        result["connection_id"],
    )
    assert conn["kind"] == "gdrive"
    assert conn["name"] == "Backups"
    cfg = conn["config"] if isinstance(conn["config"], dict) else json.loads(conn["config"])
    assert cfg["folder_id"] == "folder-XYZ"
    assert cfg["user_email"] == "ops@example.com"
    assert cfg["credentials_ref"].startswith("${vault://")

    # Pending row marquée consumed
    pending = await fetch_one(
        "SELECT consumed_at FROM oauth_pending_session WHERE state = $1", state,
    )
    assert pending["consumed_at"] is not None

    # Vault contient le secret au bon path
    creds_in_vault = vault_mock.get(
        f"remote_backups/{result['connection_id']}/oauth"
    )
    creds_dict = json.loads(creds_in_vault)
    assert creds_dict["refresh_token"] == "1//refresh-token"
    assert creds_dict["client_secret"] == "GOCSPX-secret"


@pytest.mark.asyncio
async def test_consume_session_rejects_unknown_state(fresh_db, vault_mock) -> None:
    with pytest.raises(gdrive_oauth_session.PendingSessionError, match="not found"):
        await gdrive_oauth_session.consume_session(state="unknown", code="x")


@pytest.mark.asyncio
async def test_consume_session_rejects_already_consumed(fresh_db, vault_mock) -> None:
    actor = await _create_admin_user()
    await _create_default_vault()
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://x", "x")
    fake_flow.credentials = MagicMock(
        refresh_token="rt", token_uri="https://x", client_id="c", client_secret="s",
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    fake_drive = MagicMock()
    fake_drive.files().list().execute.return_value = {"files": []}
    fake_drive.files().create().execute.return_value = {"id": "f"}

    with (
        patch("agflow.services.gdrive_oauth_session.gdrive_client.build_flow", return_value=fake_flow),
        patch("agflow.services.gdrive_oauth_session.gdrive_client.build_drive_service", return_value=fake_drive),
        patch("agflow.services.gdrive_oauth_session.gdrive_client.fetch_user_email", return_value="u@x"),
    ):
        state, _ = await gdrive_oauth_session.start_session(
            actor_user_id=actor, name="n", folder_name="f",
            client_id="c", client_secret="s", redirect_uri="r",
        )
        await gdrive_oauth_session.consume_session(state=state, code="c")
        with pytest.raises(gdrive_oauth_session.PendingSessionError, match="already consumed"):
            await gdrive_oauth_session.consume_session(state=state, code="c")


@pytest.mark.asyncio
async def test_consume_session_appends_date_suffix_if_folder_name_exists(
    fresh_db, vault_mock,
) -> None:
    actor = await _create_admin_user()
    await _create_default_vault()
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://x", "x")
    fake_flow.credentials = MagicMock(
        refresh_token="rt", token_uri="https://x", client_id="c", client_secret="s",
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    fake_drive = MagicMock()
    # Le folder demandé existe déjà → suffixe daté
    fake_drive.files().list().execute.return_value = {"files": [{"id": "existing", "name": "agflow-backups"}]}
    fake_drive.files().create().execute.return_value = {"id": "folder-NEW"}

    with (
        patch("agflow.services.gdrive_oauth_session.gdrive_client.build_flow", return_value=fake_flow),
        patch("agflow.services.gdrive_oauth_session.gdrive_client.build_drive_service", return_value=fake_drive),
        patch("agflow.services.gdrive_oauth_session.gdrive_client.fetch_user_email", return_value="u@x"),
    ):
        state, _ = await gdrive_oauth_session.start_session(
            actor_user_id=actor, name="n", folder_name="agflow-backups",
            client_id="c", client_secret="s", redirect_uri="r",
        )
        await gdrive_oauth_session.consume_session(state=state, code="c")

    # files().create a été appelé avec un nom différent (avec suffixe daté)
    create_call = fake_drive.files().create.call_args
    created_name = create_call.kwargs["body"]["name"]
    assert created_name.startswith("agflow-backups (")
    assert created_name.endswith(")")
