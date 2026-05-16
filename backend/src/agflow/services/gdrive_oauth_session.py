"""Orchestration du flow OAuth Google Drive.

start_session    : ouvre une pending row + URL Google d'autorisation
consume_session  : callback Google → INSERT connection + push vault (task 11)
get_session      : polling de status pour le frontend (task 12)
reauthorize      : re-démarre le flow pour une connexion existante (task 13)
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from uuid import UUID

import structlog

from agflow.config import get_settings
from agflow.db.pool import execute
from agflow.services.remote_backup_providers import gdrive_client

_log = structlog.get_logger(__name__)

_PENDING_TTL = timedelta(minutes=10)


def _require_dek() -> str:
    dek = get_settings().harpocrate_dek
    if not dek:
        raise RuntimeError("HARPOCRATE_DEK is not configured")
    return dek


async def start_session(
    *,
    actor_user_id: UUID,
    name: str,
    folder_name: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> tuple[str, str]:
    """Crée une pending row + retourne (state, authorize_url Google)."""
    dek = _require_dek()
    state = secrets.token_urlsafe(32)
    expires_at = datetime.now(datetime.UTC) + _PENDING_TTL

    flow = gdrive_client.build_flow(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    authorize_url, _state_unused = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        include_granted_scopes="false",
        state=state,
    )

    form_data = {
        "name": name,
        "folder_name": folder_name,
        "client_id": client_id,
    }
    await execute(
        """
        INSERT INTO oauth_pending_session
            (state, kind, actor_user_id, redirect_uri,
             form_data, client_secret_encrypted, expires_at)
        VALUES ($1, 'gdrive', $2, $3, $4::jsonb, PGP_SYM_ENCRYPT($5, $6), $7)
        """,
        state, actor_user_id, redirect_uri,
        json.dumps(form_data), client_secret, dek, expires_at,
    )
    _log.info(
        "remote_backup.gdrive.oauth_started",
        state=state, name=name, folder_name=folder_name,
        actor_user_id=str(actor_user_id),
    )
    return state, authorize_url


async def consume_session(*, state: str, code: str) -> dict:
    raise NotImplementedError("Task 11")


async def get_session(state: str) -> dict | None:
    raise NotImplementedError("Task 12")


async def reauthorize(*, connection_id: UUID, actor_user_id: UUID) -> tuple[str, str]:
    raise NotImplementedError("Task 13")
