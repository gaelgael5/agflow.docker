"""Orchestration du flow OAuth Google Drive.

start_session    : ouvre une pending row + URL Google d'autorisation
consume_session  : callback Google → INSERT connection + push vault (task 11)
get_session      : polling de status pour le frontend (task 12)
reauthorize      : re-démarre le flow pour une connexion existante (task 13)
"""
from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import structlog

from agflow.config import get_settings
from agflow.db.pool import execute, fetch_one
from agflow.services import vault_client
from agflow.services.remote_backup_providers import gdrive_client

_log = structlog.get_logger(__name__)

_PENDING_TTL = timedelta(minutes=10)


class PendingSessionError(Exception):
    """État OAuth introuvable / déjà consommé / expiré."""


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
    expires_at = datetime.now(UTC) + _PENDING_TTL

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
    dek = _require_dek()

    # 1. Lookup pending row + déchiffrement client_secret
    row = await fetch_one(
        """
        SELECT id, actor_user_id, redirect_uri, form_data,
               PGP_SYM_DECRYPT(client_secret_encrypted, $2) AS client_secret,
               expires_at, consumed_at
        FROM oauth_pending_session WHERE state = $1 AND kind = 'gdrive'
        """,
        state, dek,
    )
    if row is None:
        raise PendingSessionError(f"OAuth state not found: {state[:8]}...")
    if row["consumed_at"] is not None:
        raise PendingSessionError(f"OAuth state already consumed: {state[:8]}...")
    if row["expires_at"] < datetime.now(UTC):
        raise PendingSessionError(f"OAuth state expired: {state[:8]}...")

    form_data = row["form_data"]
    if isinstance(form_data, str):
        form_data = json.loads(form_data)

    # 2. Marquer consumed_at AVANT échange (idempotence stricte)
    await execute(
        "UPDATE oauth_pending_session SET consumed_at = now() WHERE id = $1",
        row["id"],
    )

    # 3. Échanger code → tokens
    flow = gdrive_client.build_flow(
        client_id=form_data["client_id"],
        client_secret=row["client_secret"],
        redirect_uri=row["redirect_uri"],
    )
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        _log.warning(
            "remote_backup.gdrive.oauth_failed",
            state=state[:8] + "...", error=str(exc)[:200],
        )
        raise PendingSessionError(f"OAuth token exchange failed: {exc}") from exc

    creds = flow.credentials

    # 4. Fetch user_email
    user_email = await gdrive_client.fetch_user_email(creds)

    # 5. Folder resolution : always-create avec suffixe daté si conflit
    folder_id = await _create_drive_folder(
        creds=creds, folder_name=form_data["folder_name"],
    )

    # 6. Génère l'UUID de la connexion (pour le path vault)
    connection_id = uuid4()

    # 7. Push credentials dans Harpocrate
    default_vault = await _require_default_vault_name()
    creds_payload = {
        "client_id": form_data["client_id"],
        "client_secret": row["client_secret"],
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "scope": creds.scopes[0] if creds.scopes else "",
        "granted_at": datetime.now(UTC).isoformat(),
    }
    vault_path = f"remote_backups/{connection_id}/oauth"
    await vault_client.create_secret(
        vault_path, json.dumps(creds_payload), vault_name=default_vault,
    )
    credentials_ref = vault_client.build_ref(default_vault, vault_path)

    # 8. INSERT connection
    config = {
        "client_id": form_data["client_id"],
        "redirect_uri": row["redirect_uri"],
        "folder_name": form_data["folder_name"],
        "folder_id": folder_id,
        "user_email": user_email,
        "credentials_ref": credentials_ref,
    }
    await execute(
        """
        INSERT INTO remote_backup_connections
            (id, name, kind, config, created_by_user_id)
        VALUES ($1, $2, 'gdrive', $3::jsonb, $4)
        """,
        connection_id, form_data["name"], json.dumps(config), row["actor_user_id"],
    )

    _log.info(
        "remote_backup.gdrive.oauth_completed",
        connection_id=str(connection_id), user_email=user_email,
        folder_id=folder_id, actor_user_id=str(row["actor_user_id"]),
    )

    return {
        "connection_id": connection_id,
        "user_email": user_email,
        "folder_id": folder_id,
    }


async def _require_default_vault_name() -> str:
    from agflow.services import harpocrate_vaults_service

    default = await harpocrate_vaults_service.get_default()
    if default is None:
        raise PendingSessionError(
            "No default Harpocrate vault configured — see /settings"
        )
    return default.name


async def _create_drive_folder(*, creds: object, folder_name: str) -> str:
    """Crée toujours un nouveau folder. Si `folder_name` existe déjà → suffixe daté."""
    import asyncio

    def _sync() -> str:
        service = gdrive_client.build_drive_service(creds)
        # Check si nom existe
        existing = (
            service.files()
            .list(
                q=(
                    f"name='{folder_name}' "
                    f"and mimeType='application/vnd.google-apps.folder' "
                    f"and trashed=false"
                ),
                fields="files(id, name)",
                pageSize=1,
            )
            .execute()
        )
        if existing.get("files"):
            ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
            name_to_use = f"{folder_name} ({ts})"
        else:
            name_to_use = folder_name
        created = (
            service.files()
            .create(
                body={
                    "name": name_to_use,
                    "mimeType": "application/vnd.google-apps.folder",
                },
                fields="id",
            )
            .execute()
        )
        return str(created["id"])

    return await asyncio.to_thread(_sync)


async def get_session(state: str) -> dict | None:
    """Retourne le status d'un pending session (pour polling frontend)."""
    row = await fetch_one(
        """
        SELECT consumed_at, expires_at, form_data
        FROM oauth_pending_session WHERE state = $1
        """,
        state,
    )
    if row is None:
        return None

    connection_id = None
    user_email = None
    folder_id = None
    if row["consumed_at"] is not None:
        fd = row["form_data"] if isinstance(row["form_data"], dict) else json.loads(row["form_data"])
        conn = await fetch_one(
            """
            SELECT id, config
            FROM remote_backup_connections
            WHERE kind = 'gdrive' AND name = $1 AND deleted_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            fd.get("name"),
        )
        if conn is not None:
            connection_id = conn["id"]
            cfg = conn["config"] if isinstance(conn["config"], dict) else json.loads(conn["config"])
            user_email = cfg.get("user_email")
            folder_id = cfg.get("folder_id")

    return {
        "status": "completed" if row["consumed_at"] else "pending",
        "connection_id": connection_id,
        "user_email": user_email,
        "folder_id": folder_id,
    }


async def reauthorize(
    *, connection_id: UUID, actor_user_id: UUID,
) -> tuple[str, str]:
    """Re-démarre le flow OAuth pour une connexion gdrive existante.

    Le `client_id` est récupéré depuis `config`, le `client_secret` est
    déchiffré depuis Harpocrate puis ré-encrypté dans la pending row.
    """
    row = await fetch_one(
        "SELECT name, kind, config FROM remote_backup_connections WHERE id = $1",
        connection_id,
    )
    if row is None:
        raise PendingSessionError(f"Connection {connection_id} not found")
    if row["kind"] != "gdrive":
        raise PendingSessionError(
            f"Connection {connection_id} has kind {row['kind']!r}, not gdrive"
        )
    cfg = row["config"] if isinstance(row["config"], dict) else json.loads(row["config"])

    creds_ref = cfg.get("credentials_ref")
    if not creds_ref:
        raise PendingSessionError(
            f"Connection {connection_id} missing credentials_ref in config"
        )
    creds_raw = await vault_client.resolve_ref(creds_ref)
    creds_data = json.loads(creds_raw)
    client_secret = creds_data["client_secret"]

    return await start_session(
        actor_user_id=actor_user_id,
        name=row["name"],
        folder_name=cfg["folder_name"],
        client_id=cfg["client_id"],
        client_secret=client_secret,
        redirect_uri=cfg["redirect_uri"],
    )
