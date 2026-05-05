from __future__ import annotations

from typing import Literal

import structlog

from agflow.schemas.secrets import SecretReveal, SecretSummary
from agflow.services import vault_client

_log = structlog.get_logger(__name__)


class SecretNotFoundError(Exception):
    pass


class DuplicateSecretError(Exception):
    pass


async def list_all() -> list[SecretSummary]:
    infos = await vault_client.list_secrets(limit=200)
    return [
        SecretSummary(
            name=s.name,
            is_placeholder=s.is_placeholder,
            description=s.description,
            tags=s.tags,
        )
        for s in infos
    ]


async def reveal(name: str) -> SecretReveal:
    from harpocrate.exceptions import SecretNotFound

    try:
        value = await vault_client.get_secret(name)
    except SecretNotFound as exc:
        raise SecretNotFoundError(f"Secret '{name}' not found") from exc
    _log.info("secrets.reveal", name=name)
    return SecretReveal(name=name, value=value)


async def create(name: str, value: str) -> SecretSummary:
    from harpocrate.exceptions import VaultHttpError

    try:
        await vault_client.create_secret(name, value)
    except VaultHttpError as exc:
        if exc.status_code == 409:
            raise DuplicateSecretError(f"Secret '{name}' already exists") from exc
        raise
    _log.info("secrets.create", name=name)
    return SecretSummary(name=name)


async def update(name: str, value: str) -> None:
    from harpocrate.exceptions import SecretNotFound

    try:
        await vault_client.update_secret(name, value)
    except SecretNotFound as exc:
        raise SecretNotFoundError(f"Secret '{name}' not found") from exc
    _log.info("secrets.update", name=name)


async def delete(name: str) -> None:
    from harpocrate.exceptions import SecretNotFound

    try:
        await vault_client.delete_secret(name)
    except SecretNotFound as exc:
        raise SecretNotFoundError(f"Secret '{name}' not found") from exc
    _log.info("secrets.delete", name=name)


async def resolve_env(var_names: list[str]) -> dict[str, str]:
    """Résout les noms de secrets en valeurs déchiffrées. Lève si l'un manque."""
    from harpocrate.exceptions import SecretNotFound

    result: dict[str, str] = {}
    missing: list[str] = []
    for name in var_names:
        try:
            result[name] = await vault_client.get_secret(name)
        except SecretNotFound:
            missing.append(name)
    if missing:
        raise SecretNotFoundError(f"Missing secrets: {', '.join(missing)}")
    return result


async def resolve_status(
    var_names: list[str],
) -> dict[str, Literal["ok", "empty", "missing"]]:
    """Retourne le statut de chaque variable (pour indicateurs visuels 🔴🟠🟢)."""
    from harpocrate.exceptions import SecretNotFound

    result: dict[str, Literal["ok", "empty", "missing"]] = {}
    for name in var_names:
        try:
            value = await vault_client.get_secret(name)
            result[name] = "ok" if value.strip() else "empty"
        except SecretNotFound:
            result[name] = "missing"
    return result
