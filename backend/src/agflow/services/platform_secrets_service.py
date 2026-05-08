from __future__ import annotations

import contextlib
import re
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.platform_secrets import PlatformSecretReveal, PlatformSecretSummary
from agflow.services import vault_client

_log = structlog.get_logger(__name__)

VAULT_API_KEY_ID = "HARPOCRATE_KEY"


class PlatformSecretNotFoundError(Exception):
    pass


class DuplicatePlatformSecretError(Exception):
    pass


def _vault_key(name: str) -> str:
    return f"${{vault://{VAULT_API_KEY_ID}:{name}}}"


def _env_key(name: str) -> str:
    return f"${{env://{name}}}"


def _parse_vault_name(key: str) -> str:
    """Extrait le nom depuis '${vault://HARPOCRATE_KEY:NAME}'."""
    inner = key[len("${vault://"):-1]
    _, name = inner.split(":", 1)
    return name


def _parse_env_name(key: str) -> str:
    """Extrait le nom depuis '${env://NAME}'."""
    return key[len("${env://"):-1]


def _row_to_summary(row: dict) -> PlatformSecretSummary:
    key: str = row["key"]
    if key.startswith("${vault://"):
        return PlatformSecretSummary(
            id=row["id"],
            key=key,
            type="vault",
            name=_parse_vault_name(key),
            has_value=row["default_value"] == "set",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    return PlatformSecretSummary(
        id=row["id"],
        key=key,
        type="env",
        name=_parse_env_name(key),
        has_value=row["default_value"] is not None and row["default_value"] != "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_all() -> list[PlatformSecretSummary]:
    rows = await fetch_all(
        "SELECT id, key, default_value, created_at, updated_at "
        "FROM platform_secrets ORDER BY created_at ASC"
    )
    return [_row_to_summary(r) for r in rows]


async def create_vault(name: str, value: str) -> PlatformSecretSummary:
    import asyncpg
    key = _vault_key(name)
    sentinel = "set" if value else None
    try:
        row = await fetch_one(
            "INSERT INTO platform_secrets (key, default_value) VALUES ($1, $2) "
            "RETURNING id, key, default_value, created_at, updated_at",
            key,
            sentinel,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicatePlatformSecretError(f"'{name}' existe déjà") from exc
    assert row is not None
    if value:
        await vault_client.create_secret(name, value)
    _log.info("platform_secrets.create_vault", name=name, has_value=bool(value))
    return _row_to_summary(row)


async def create_env(name: str, value: str) -> PlatformSecretSummary:
    import asyncpg
    key = _env_key(name)
    try:
        row = await fetch_one(
            "INSERT INTO platform_secrets (key, default_value) VALUES ($1, $2) "
            "RETURNING id, key, default_value, created_at, updated_at",
            key,
            value or None,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicatePlatformSecretError(f"'{name}' existe déjà") from exc
    assert row is not None
    _log.info("platform_secrets.create_env", name=name)
    return _row_to_summary(row)


async def update(secret_id: UUID, value: str) -> None:
    row = await fetch_one(
        "SELECT key, default_value FROM platform_secrets WHERE id = $1", secret_id
    )
    if row is None:
        raise PlatformSecretNotFoundError(f"Secret '{secret_id}' introuvable")
    key: str = row["key"]
    if key.startswith("${vault://"):
        name = _parse_vault_name(key)
        # default_value == "set" means a vault entry already exists; otherwise first write
        if row["default_value"] == "set":
            await vault_client.update_secret(name, value)
        else:
            await vault_client.create_secret(name, value)
        await execute(
            "UPDATE platform_secrets SET default_value = 'set' WHERE id = $1",
            secret_id,
        )
    else:
        await execute(
            "UPDATE platform_secrets SET default_value = $2 WHERE id = $1",
            secret_id,
            value or None,
        )
    _log.info("platform_secrets.update", secret_id=str(secret_id))


async def delete(secret_id: UUID) -> None:
    row = await fetch_one(
        "SELECT key FROM platform_secrets WHERE id = $1", secret_id
    )
    if row is None:
        raise PlatformSecretNotFoundError(f"Secret '{secret_id}' introuvable")
    key: str = row["key"]
    if key.startswith("${vault://"):
        with contextlib.suppress(Exception):
            await vault_client.delete_secret(_parse_vault_name(key))
    await execute("DELETE FROM platform_secrets WHERE id = $1", secret_id)
    _log.info("platform_secrets.delete", secret_id=str(secret_id))


async def reveal(secret_id: UUID) -> PlatformSecretReveal:
    row = await fetch_one(
        "SELECT id, key, default_value FROM platform_secrets WHERE id = $1",
        secret_id,
    )
    if row is None:
        raise PlatformSecretNotFoundError(f"Secret '{secret_id}' introuvable")
    key: str = row["key"]
    if key.startswith("${vault://"):
        name = _parse_vault_name(key)
        value = await vault_client.get_secret(name)
        return PlatformSecretReveal(id=row["id"], name=name, value=value)
    name = _parse_env_name(key)
    return PlatformSecretReveal(id=row["id"], name=name, value=row["default_value"] or "")


async def resolve_all() -> dict[str, str]:
    """Résout toutes les entrées vers {nom_variable: valeur} pour l'injection container."""
    rows = await fetch_all("SELECT key, default_value FROM platform_secrets")
    result: dict[str, str] = {}
    for row in rows:
        key: str = row["key"]
        if key.startswith("${vault://"):
            name = _parse_vault_name(key)
            if row["default_value"] != "set":
                continue
            try:
                result[name] = await vault_client.get_secret(name)
            except Exception:
                _log.warning("platform_secrets.resolve.vault_miss", name=name)
        else:
            name = _parse_env_name(key)
            result[name] = row["default_value"] or ""
    return result


_VAULT_REF_RE = re.compile(r"\$\{vault://[^:}]+:([^}]+)\}")
_ENV_REF_RE = re.compile(r"\$\{env://([^}]+)\}")


def resolve_platform_refs(text: str, secrets: dict[str, str]) -> str:
    """Résout ${vault://KEY:NAME} et ${env://NAME} dans text.

    secrets = résultat de resolve_all() : {nom_variable: valeur}.
    Les références inconnues sont remplacées par une chaîne vide.
    """
    text = _VAULT_REF_RE.sub(lambda m: secrets.get(m.group(1), ""), text)
    text = _ENV_REF_RE.sub(lambda m: secrets.get(m.group(1), ""), text)
    return text
