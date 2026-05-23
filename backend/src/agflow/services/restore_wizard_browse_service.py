from __future__ import annotations

import stat as stat_mod
from datetime import datetime, timezone

import structlog

from agflow.schemas.restore_wizard import RemoteEntry
from agflow.services.remote_backup_providers.factory import get_provider

_log = structlog.get_logger(__name__)


async def browse_remote(
    connection_type: str,
    manual_fields: dict[str, str],
    credentials: dict[str, str | None],
) -> list[RemoteEntry]:
    """Liste les entrées (fichiers + dossiers) d'un path distant.

    SFTP : navigation répertoire complète via asyncssh.
    Autres providers : liste plate via list_remote existant.
    """
    path = manual_fields.get("path", "/")
    if connection_type == "sftp":
        return await _browse_sftp(manual_fields, credentials, path)
    return await _browse_via_provider(connection_type, manual_fields, credentials, path)


async def _browse_sftp(
    config: dict[str, str],
    credentials: dict[str, str | None],
    path: str,
) -> list[RemoteEntry]:
    import asyncssh

    host = config["host"]
    port = int(config.get("port", "22"))
    username = credentials.get("username", "")
    password = credentials.get("password")
    private_key_str = credentials.get("private_key")
    passphrase = credentials.get("passphrase")

    connect_kwargs: dict = {
        "host": host,
        "port": port,
        "username": username,
        "known_hosts": None,
    }
    if private_key_str:
        import asyncssh as _ssh

        pkey = _ssh.import_private_key(
            private_key_str,
            passphrase=passphrase.encode() if passphrase else None,
        )
        connect_kwargs["client_keys"] = [pkey]
    elif password:
        connect_kwargs["password"] = password

    async with asyncssh.connect(**connect_kwargs) as conn:
        async with conn.start_sftp_client() as sftp:
            raw = await sftp.readdir(path)

    entries: list[RemoteEntry] = []
    for entry in raw:
        if entry.filename in (".", ".."):
            continue
        perms = getattr(entry.attrs, "permissions", None) or 0
        is_dir = stat_mod.S_ISDIR(perms)
        mtime = getattr(entry.attrs, "mtime", None)
        size = getattr(entry.attrs, "size", None)
        entries.append(
            RemoteEntry(
                name=entry.filename,
                path=path.rstrip("/") + "/" + entry.filename,
                is_dir=is_dir,
                size_bytes=None if is_dir else size,
                modified_at=(
                    datetime.fromtimestamp(mtime, tz=timezone.utc) if mtime else None
                ),
            )
        )
    return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))


async def _browse_via_provider(
    kind: str,
    config: dict[str, str],
    credentials: dict[str, str | None],
    path: str,
) -> list[RemoteEntry]:
    provider = get_provider(kind, config, credentials)
    files = await provider.list_remote(path)
    return [
        RemoteEntry(
            name=f.filename,
            path=path.rstrip("/") + "/" + f.filename,
            is_dir=False,
            size_bytes=f.size_bytes,
            modified_at=f.last_modified,
        )
        for f in files
    ]
