"""CRUD des coffres Harpocrate stockés en DB.

La clé API de chaque coffre est chiffrée au repos avec pgcrypto
(`PGP_SYM_ENCRYPT` / `PGP_SYM_DECRYPT_TEXT`). La passphrase vient de
`settings.harpocrate_dek` — sans elle, le service refuse toute opération
qui implique le chiffrement/déchiffrement.

Le flag `is_default` est unique (partial unique index côté DB). Le service
`set_default` réalise l'opération de manière atomique dans une transaction.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.config import get_settings
from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.harpocrate_vaults import (
    VaultCreateRequest,
    VaultSummary,
    VaultTestConnectionResult,
    VaultUpdateRequest,
)

_log = structlog.get_logger(__name__)

_COLS = "id, name, base_url, api_key_id, is_default, created_at, updated_at"


class VaultNotFoundError(Exception):
    pass


class DuplicateVaultNameError(Exception):
    pass


class NoDekConfiguredError(Exception):
    """Levée quand HARPOCRATE_DEK est vide → impossible de chiffrer/déchiffrer."""


def _require_dek() -> str:
    dek = get_settings().harpocrate_dek
    if not dek:
        raise NoDekConfiguredError(
            "HARPOCRATE_DEK is not configured — cannot encrypt/decrypt vault api_keys"
        )
    return dek


def _to_summary(row: dict[str, Any]) -> VaultSummary:
    return VaultSummary(
        id=row["id"],
        name=row["name"],
        base_url=row["base_url"],
        api_key_id=row["api_key_id"],
        is_default=row["is_default"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_all() -> list[VaultSummary]:
    rows = await fetch_all(f"SELECT {_COLS} FROM harpocrate_vaults ORDER BY name")
    return [_to_summary(r) for r in rows]


async def get_by_id(vault_id: UUID) -> VaultSummary:
    row = await fetch_one(
        f"SELECT {_COLS} FROM harpocrate_vaults WHERE id = $1", vault_id,
    )
    if row is None:
        raise VaultNotFoundError(f"Vault {vault_id} not found")
    return _to_summary(row)


async def get_by_name(name: str) -> VaultSummary | None:
    row = await fetch_one(
        f"SELECT {_COLS} FROM harpocrate_vaults WHERE name = $1", name,
    )
    return _to_summary(row) if row else None


async def get_default() -> VaultSummary | None:
    row = await fetch_one(
        f"SELECT {_COLS} FROM harpocrate_vaults WHERE is_default = true",
    )
    return _to_summary(row) if row else None


async def reveal_api_key(vault_id: UUID) -> str:
    """Déchiffre et retourne la clé API d'un coffre. Internal-only.

    Utilisé par `vault_client` pour instancier un `harpocrate.VaultClient`.
    NE JAMAIS retourner ce résultat via une route HTTP.
    """
    dek = _require_dek()
    row = await fetch_one(
        """
        SELECT PGP_SYM_DECRYPT(api_key_encrypted, $2) AS api_key
        FROM harpocrate_vaults
        WHERE id = $1
        """,
        vault_id, dek,
    )
    if row is None:
        raise VaultNotFoundError(f"Vault {vault_id} not found")
    return row["api_key"]


async def create(payload: VaultCreateRequest) -> VaultSummary:
    """Crée un nouveau coffre. Si `is_default=True`, le flag est déplacé atomiquement."""
    dek = _require_dek()
    existing = await get_by_name(payload.name)
    if existing is not None:
        raise DuplicateVaultNameError(f"Vault '{payload.name}' already exists")

    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        if payload.is_default:
            await conn.execute(
                "UPDATE harpocrate_vaults SET is_default = false WHERE is_default = true"
            )
        row = await conn.fetchrow(
            f"""
                INSERT INTO harpocrate_vaults
                    (name, base_url, api_key_id, api_key_encrypted, is_default)
                VALUES ($1, $2, $3, PGP_SYM_ENCRYPT($4, $5), $6)
                RETURNING {_COLS}
                """,
            payload.name, str(payload.base_url), payload.api_key_id,
            payload.api_key, dek, payload.is_default,
        )
    assert row is not None
    _log.info(
        "harpocrate_vaults.create",
        vault_id=str(row["id"]), name=payload.name, is_default=payload.is_default,
    )
    return _to_summary(row)


async def update(vault_id: UUID, payload: VaultUpdateRequest) -> VaultSummary:
    """Met à jour un coffre. Tous les champs sont optionnels.

    Si `api_key` est fourni, la clé est ré-chiffrée. Si `is_default=True`,
    le flag est déplacé atomiquement vers ce coffre.
    """
    await get_by_id(vault_id)
    needs_dek = payload.api_key is not None
    dek = _require_dek() if needs_dek else ""

    if payload.name is not None:
        clash = await get_by_name(payload.name)
        if clash is not None and clash.id != vault_id:
            raise DuplicateVaultNameError(f"Vault '{payload.name}' already exists")

    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        if payload.is_default is True:
            await conn.execute(
                "UPDATE harpocrate_vaults SET is_default = false WHERE is_default = true AND id != $1",
                vault_id,
            )

        sets: list[str] = []
        args: list[Any] = [vault_id]
        i = 2

        if payload.name is not None:
            sets.append(f"name = ${i}")
            args.append(payload.name)
            i += 1
        if payload.base_url is not None:
            sets.append(f"base_url = ${i}")
            args.append(str(payload.base_url))
            i += 1
        if payload.api_key_id is not None:
            sets.append(f"api_key_id = ${i}")
            args.append(payload.api_key_id)
            i += 1
        if payload.api_key is not None:
            sets.append(f"api_key_encrypted = PGP_SYM_ENCRYPT(${i}, ${i + 1})")
            args.extend([payload.api_key, dek])
            i += 2
        if payload.is_default is not None:
            sets.append(f"is_default = ${i}")
            args.append(payload.is_default)
            i += 1

        if not sets:
            row = await conn.fetchrow(
                f"SELECT {_COLS} FROM harpocrate_vaults WHERE id = $1", vault_id,
            )
        else:
            row = await conn.fetchrow(
                f"UPDATE harpocrate_vaults SET {', '.join(sets)} "
                f"WHERE id = $1 RETURNING {_COLS}",
                *args,
            )
    assert row is not None
    _log.info("harpocrate_vaults.update", vault_id=str(vault_id))
    return _to_summary(row)


async def delete(vault_id: UUID) -> None:
    row = await fetch_one(
        "DELETE FROM harpocrate_vaults WHERE id = $1 RETURNING id", vault_id,
    )
    if row is None:
        raise VaultNotFoundError(f"Vault {vault_id} not found")
    _log.info("harpocrate_vaults.delete", vault_id=str(vault_id))


async def set_default(vault_id: UUID) -> VaultSummary:
    """Marque le coffre `vault_id` comme default ; déclasse tous les autres.

    Opération atomique (transaction). Si le coffre est déjà default, no-op.
    """
    await get_by_id(vault_id)

    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE harpocrate_vaults SET is_default = false WHERE is_default = true AND id != $1",
            vault_id,
        )
        row = await conn.fetchrow(
            f"UPDATE harpocrate_vaults SET is_default = true "
            f"WHERE id = $1 RETURNING {_COLS}",
            vault_id,
        )
    assert row is not None
    _log.info("harpocrate_vaults.set_default", vault_id=str(vault_id))
    return _to_summary(row)


async def test_connection(vault_id: UUID) -> VaultTestConnectionResult:
    """Tente un `/whoami` sur le coffre via le SDK Harpocrate.

    Le résultat ne contient jamais la clé API. En cas d'échec, le message
    d'erreur est tronqué à 200 chars pour éviter de leaker des détails
    sensibles via une route HTTP authentifiée.
    """
    summary = await get_by_id(vault_id)

    try:
        api_key = await reveal_api_key(vault_id)
    except NoDekConfiguredError as exc:
        return VaultTestConnectionResult(ok=False, error=str(exc))

    # Import local : `harpocrate` est un dep optionnelle au démarrage.
    import asyncio

    from harpocrate import VaultClient

    def _whoami() -> None:
        client = VaultClient(token=api_key, base_url=summary.base_url)
        client.whoami()

    try:
        await asyncio.to_thread(_whoami)
    except Exception as exc:
        msg = str(exc)[:200]
        _log.warning(
            "harpocrate_vaults.test_connection_failed",
            vault_id=str(vault_id), error=msg,
        )
        return VaultTestConnectionResult(ok=False, error=msg)

    return VaultTestConnectionResult(ok=True)


__all__ = [
    "DuplicateVaultNameError",
    "NoDekConfiguredError",
    "VaultNotFoundError",
    "create",
    "delete",
    "get_by_id",
    "get_by_name",
    "get_default",
    "list_all",
    "reveal_api_key",
    "set_default",
    "test_connection",
    "update",
]
