from __future__ import annotations

import json
from uuid import UUID, uuid4

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.remote_backup_connections import RemoteBackupConnectionSummary
from agflow.services import vault_client

_log = structlog.get_logger(__name__)


async def _require_vault_name(vault_name: str | None) -> str:
    """Retourne vault_name s'il est fourni, sinon le coffre par défaut. Lève si aucun configuré."""
    if vault_name is not None:
        return vault_name
    from agflow.services import harpocrate_vaults_service
    default = await harpocrate_vaults_service.get_default()
    if default is None:
        raise vault_client.VaultNotFoundError(
            "No default Harpocrate vault configured — see /settings"
        )
    return default.name


async def _read_vault_credentials(stored: str) -> dict:
    """Lit un secret credentials depuis Harpocrate.
    `stored` peut être un vault ref (${vault://name:path}) ou un chemin nu (rétrocompat).
    """
    parsed = vault_client.parse_ref(stored)
    if parsed:
        vname, path = parsed
        raw = await vault_client.get_secret(path, vault_name=vname)
    else:
        raw = await vault_client.get_secret(stored)
    return json.loads(raw)


async def _delete_vault_credentials(stored: str) -> None:
    parsed = vault_client.parse_ref(stored)
    if parsed:
        vname, path = parsed
        await vault_client.delete_secret(path, vault_name=vname)
    else:
        await vault_client.delete_secret(stored)

# ─── helpers DB internes (facilement mockables dans les tests) ─────────────
#
# Note : execute/fetch_all/fetch_one du pool acquièrent leur propre connexion
# et ne supportent pas de paramètre conn externe. Le paramètre conn présent
# dans l'API publique (list_connections, get_connection, …) est conservé pour
# compatibilité avec les appelants (routers) mais n'est pas transmis ici.


async def _insert_row(*, connection_id: UUID, name: str, kind: str,
                      config: dict, vault_api_key_id: str | None,
                      vault_secret_path: str | None,
                      created_by_user_id: UUID | None) -> None:
    # Le codec JSONB du pool gère l'encodage dict → JSON automatiquement.
    await execute(
        """
        INSERT INTO remote_backup_connections
            (id, name, kind, config, vault_api_key_id, vault_secret_path, created_by_user_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        connection_id, name, kind, config,
        vault_api_key_id, vault_secret_path, created_by_user_id,
    )


async def _fetch_all_rows() -> list[dict]:
    return await fetch_all(
        "SELECT id, name, kind, config, vault_api_key_id, vault_secret_path, "
        "       created_at, updated_at, "
        "       (vault_secret_path IS NOT NULL) AS has_credentials "
        "FROM remote_backup_connections "
        "WHERE deleted_at IS NULL ORDER BY name"
    )


async def _fetch_row_by_id(connection_id: UUID) -> dict | None:
    return await fetch_one(
        "SELECT id, name, kind, config, vault_api_key_id, vault_secret_path, "
        "       created_at, updated_at, "
        "       (vault_secret_path IS NOT NULL) AS has_credentials "
        "FROM remote_backup_connections "
        "WHERE id = $1 AND deleted_at IS NULL",
        connection_id,
    )


async def _soft_delete_row(connection_id: UUID) -> None:
    await execute(
        "UPDATE remote_backup_connections SET deleted_at = NOW() WHERE id = $1",
        connection_id,
    )


def _to_dto(row: dict) -> RemoteBackupConnectionSummary:
    # Le codec JSONB du pool décode toujours en dict ; la branche json.loads
    # reste en défense pour les cas où le champ serait une string brute.
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
    rows = await _fetch_all_rows()
    return [_to_dto(r) for r in rows]


async def get_connection(conn, connection_id: UUID) -> RemoteBackupConnectionSummary | None:
    row = await _fetch_row_by_id(connection_id)
    return _to_dto(row) if row else None


async def fetch_credentials(connection: RemoteBackupConnectionSummary) -> dict | None:
    """Lit les credentials depuis Harpocrate. NE PAS appeler dans les listings."""
    if not connection.has_credentials:
        return None
    row = await _fetch_row_by_id(connection.id)
    if row is None:
        return None
    stored = row.get("vault_secret_path") or f"remote-backups/{connection.id}"
    return await _read_vault_credentials(stored)


async def create_connection(
    conn,
    *,
    name: str,
    kind: str,
    config: dict,
    credentials: dict | None,
    created_by_user_id: UUID | None = None,
    vault_name: str | None = None,
) -> UUID:
    connection_id = uuid4()
    vault_secret_path: str | None = None

    if credentials:
        vname = await _require_vault_name(vault_name)
        path = f"remote-backups/{connection_id}"
        await vault_client.create_secret(path, json.dumps(credentials), vault_name=vname)
        vault_secret_path = vault_client.build_ref(vname, path)

    try:
        await _insert_row(
            connection_id=connection_id,
            name=name, kind=kind, config=config,
            vault_api_key_id=None,
            vault_secret_path=vault_secret_path,
            created_by_user_id=created_by_user_id,
        )
    except Exception:
        if vault_secret_path:
            try:
                await _delete_vault_credentials(vault_secret_path)
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
    vault_name: str | None = None,
) -> None:
    row = await _fetch_row_by_id(connection_id)
    if row is None:
        raise ValueError(f"Connection {connection_id} not found")

    if credentials is not None and row["vault_secret_path"]:
        stored = row["vault_secret_path"]
        parsed = vault_client.parse_ref(stored)
        if parsed:
            vname, path = parsed
            await vault_client.update_secret(path, json.dumps(credentials), vault_name=vname)
        else:
            await vault_client.update_secret(stored, json.dumps(credentials))
    elif credentials is not None:
        vname = await _require_vault_name(vault_name)
        path = f"remote-backups/{connection_id}"
        await vault_client.create_secret(path, json.dumps(credentials), vault_name=vname)
        new_ref = vault_client.build_ref(vname, path)
        try:
            await execute(
                "UPDATE remote_backup_connections SET vault_api_key_id=$1, vault_secret_path=$2 WHERE id=$3",
                None, new_ref, connection_id,
            )
        except Exception:
            try:
                await vault_client.delete_secret(path, vault_name=vname)
            except Exception as cleanup_err:
                _log.warning("rbc.vault_cleanup_failed", path=path, error=str(cleanup_err))
            raise

    updates: list[str] = []
    params: list = []
    idx = 1
    if name is not None:
        updates.append(f"name = ${idx}")
        params.append(name)
        idx += 1
    if config is not None:
        # Le codec JSONB du pool gère l'encodage dict → JSON automatiquement.
        updates.append(f"config = ${idx}")
        params.append(config)
        idx += 1

    if updates:
        params.append(connection_id)
        await execute(
            f"UPDATE remote_backup_connections SET {', '.join(updates)} WHERE id = ${idx}",
            *params,
        )
    elif credentials is not None:
        # Credentials mis à jour sans changement name/config : forcer updated_at
        # pour que les appelants voient la modification dans le champ timestamp.
        await execute(
            "UPDATE remote_backup_connections SET updated_at = NOW() WHERE id = $1",
            connection_id,
        )


async def delete_connection(conn, connection_id: UUID) -> None:
    row = await _fetch_row_by_id(connection_id)
    if row is None:
        return
    await _soft_delete_row(connection_id)
    if row["vault_secret_path"]:
        try:
            await _delete_vault_credentials(row["vault_secret_path"])
        except Exception as exc:
            _log.warning("rbc.vault_delete_failed",
                         path=row["vault_secret_path"], error=str(exc),
                         note="secret orphan in vault — cleanup manually")


async def inject_certificate_credentials(config: dict, credentials: dict) -> dict:
    """Si config["certificate_id"] est défini (SFTP), résout la clé privée depuis infra_certificates.

    Retourne credentials enrichi de private_key + passphrase (le cas échéant).
    Sans certificate_id, retourne credentials inchangé.
    """
    cert_id_str = config.get("certificate_id")
    if not cert_id_str:
        return credentials
    from uuid import UUID

    from agflow.services import infra_certificates_service
    try:
        decrypted = await infra_certificates_service.get_decrypted(UUID(str(cert_id_str)))
    except infra_certificates_service.CertificateNotFoundError as exc:
        raise ValueError(f"SSH certificate {cert_id_str}: {exc}") from exc
    extra: dict = {"private_key": decrypted["private_key"]}
    if decrypted.get("passphrase"):
        extra["passphrase"] = decrypted["passphrase"]
    return {**credentials, **extra}


def resolve_remote_path(config: dict, kind: str, usage: str) -> str | None:
    """Retourne le path côté serveur (SFTP/S3) selon kind et usage (snapshots|full)."""
    if kind in ("sftp", "ftps"):
        key = "remote_path_snapshots" if usage == "snapshots" else "remote_path_full"
    else:  # s3
        key = "prefix_snapshots" if usage == "snapshots" else "prefix_full"
    return config.get(key) or None
