from __future__ import annotations

import json
from uuid import UUID, uuid4

import structlog

from agflow.config import get_settings
from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.remote_backup_connections import RemoteBackupConnectionSummary
from agflow.services import vault_client

_log = structlog.get_logger(__name__)

# ─── helpers DB internes (facilement mockables dans les tests) ─────────────

async def _insert_row(conn, *, connection_id: UUID, name: str, kind: str,
                      config: dict, vault_api_key_id: str | None,
                      vault_secret_path: str | None,
                      created_by_user_id: UUID | None) -> None:
    await execute(
        """
        INSERT INTO remote_backup_connections
            (id, name, kind, config, vault_api_key_id, vault_secret_path, created_by_user_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        connection_id, name, kind, json.dumps(config),
        vault_api_key_id, vault_secret_path, created_by_user_id,
    )


async def _fetch_all_rows(conn) -> list[dict]:
    return await fetch_all(
        "SELECT id, name, kind, config, vault_api_key_id, vault_secret_path, "
        "       created_at, updated_at, "
        "       (vault_secret_path IS NOT NULL) AS has_credentials "
        "FROM remote_backup_connections "
        "WHERE deleted_at IS NULL ORDER BY name"
    )


async def _fetch_row_by_id(conn, connection_id: UUID) -> dict | None:
    return await fetch_one(
        "SELECT id, name, kind, config, vault_api_key_id, vault_secret_path, "
        "       created_at, updated_at, "
        "       (vault_secret_path IS NOT NULL) AS has_credentials "
        "FROM remote_backup_connections "
        "WHERE id = $1 AND deleted_at IS NULL",
        connection_id,
    )


async def _soft_delete_row(conn, connection_id: UUID) -> None:
    await execute(
        "UPDATE remote_backup_connections SET deleted_at = NOW() WHERE id = $1",
        connection_id,
    )


def _to_dto(row: dict) -> RemoteBackupConnectionSummary:
    return RemoteBackupConnectionSummary(
        id=row["id"],
        name=row["name"],
        kind=row["kind"],
        config=row["config"] if isinstance(row["config"], dict) else json.loads(row["config"]),
        has_credentials=row["has_credentials"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ─── API publique ──────────────────────────────────────────────────────────

async def list_connections(conn) -> list[RemoteBackupConnectionSummary]:
    rows = await _fetch_all_rows(conn)
    return [_to_dto(r) for r in rows]


async def get_connection(conn, connection_id: UUID) -> RemoteBackupConnectionSummary | None:
    row = await _fetch_row_by_id(conn, connection_id)
    return _to_dto(row) if row else None


async def fetch_credentials(connection: RemoteBackupConnectionSummary) -> dict | None:
    """Lit les credentials depuis Harpocrate. NE PAS appeler dans les listings."""
    if not connection.has_credentials:
        return None
    path = f"remote-backups/{connection.id}"
    raw = await vault_client.get_secret(path)
    return json.loads(raw)


async def create_connection(
    conn,
    *,
    name: str,
    kind: str,
    config: dict,
    credentials: dict | None,
    created_by_user_id: UUID | None = None,
) -> UUID:
    settings = get_settings()
    connection_id = uuid4()
    vault_api_key_id: str | None = None
    vault_secret_path: str | None = None

    if credentials:
        path = f"remote-backups/{connection_id}"
        await vault_client.create_secret(path, json.dumps(credentials))
        vault_api_key_id = settings.harpocrate_vault_api_key_id
        vault_secret_path = path

    try:
        await _insert_row(
            conn,
            connection_id=connection_id,
            name=name, kind=kind, config=config,
            vault_api_key_id=vault_api_key_id,
            vault_secret_path=vault_secret_path,
            created_by_user_id=created_by_user_id,
        )
    except Exception:
        if vault_secret_path:
            try:
                await vault_client.delete_secret(vault_secret_path)
            except Exception as cleanup_err:
                _log.warning("rbc.vault_cleanup_failed", path=vault_secret_path, error=str(cleanup_err))
        raise

    _log.info("rbc.created", connection_id=str(connection_id), kind=kind)
    return connection_id


async def update_connection(
    conn,
    connection_id: UUID,
    *,
    name: str | None = None,
    config: dict | None = None,
    credentials: dict | None = None,
) -> None:
    row = await _fetch_row_by_id(conn, connection_id)
    if row is None:
        raise ValueError(f"Connection {connection_id} not found")

    if credentials is not None and row["vault_secret_path"]:
        await vault_client.update_secret(row["vault_secret_path"], json.dumps(credentials))
    elif credentials is not None:
        settings = get_settings()
        path = f"remote-backups/{connection_id}"
        await vault_client.create_secret(path, json.dumps(credentials))
        await execute(
            "UPDATE remote_backup_connections SET vault_api_key_id=$1, vault_secret_path=$2 WHERE id=$3",
            settings.harpocrate_vault_api_key_id, path, connection_id,
        )

    updates: list[str] = []
    params: list = []
    idx = 1
    if name is not None:
        updates.append(f"name = ${idx}")
        params.append(name)
        idx += 1
    if config is not None:
        updates.append(f"config = ${idx}")
        params.append(json.dumps(config))
        idx += 1
    if updates:
        params.append(connection_id)
        await execute(
            f"UPDATE remote_backup_connections SET {', '.join(updates)} WHERE id = ${idx}",
            *params,
        )


async def delete_connection(conn, connection_id: UUID) -> None:
    row = await _fetch_row_by_id(conn, connection_id)
    if row is None:
        return
    await _soft_delete_row(conn, connection_id)
    if row["vault_secret_path"]:
        try:
            await vault_client.delete_secret(row["vault_secret_path"])
        except Exception as exc:
            _log.warning("rbc.vault_delete_failed",
                         path=row["vault_secret_path"], error=str(exc),
                         note="secret orphan in vault — cleanup manually")


def resolve_remote_path(config: dict, kind: str, usage: str) -> str | None:
    """Retourne le path côté serveur (SFTP/S3) selon kind et usage (snapshots|full)."""
    if kind in ("sftp", "ftps"):
        key = "remote_path_snapshots" if usage == "snapshots" else "remote_path_full"
    else:  # s3
        key = "prefix_snapshots" if usage == "snapshots" else "prefix_full"
    return config.get(key) or None
