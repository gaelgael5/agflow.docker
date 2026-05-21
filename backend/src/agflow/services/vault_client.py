"""Async wrapper multi-coffres autour du SDK Harpocrate synchrone.

Le client résout le coffre cible par son **nom logique** (colonne
`harpocrate_vaults.name` côté DB). Un coffre marqué `is_default = true`
peut être utilisé implicitement (sans `vault_name`).

Format des vault refs supportés :
    ${vault://<vault_name>:<secret_path>}

Au bootstrap (DB vide / pas encore migrée), un fallback lit `settings.harpocrate_key`
et `settings.harpocrate_url` pour rester compatible avec les anciens déploiements
qui n'ont pas encore créé de coffre via l'UI Settings.

Cache mémoire des `VaultClient` par nom de coffre ; `reset_cache()` invalide
le cache après une rotation de clé. Le retry 401 réinitialise aussi.
"""
from __future__ import annotations

import asyncio
import re
from functools import partial
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from harpocrate import VaultClient

_log = structlog.get_logger(__name__)

_VAULT_REF_RE = re.compile(r"^\$\{vault://([^:]+):(.+)\}$")
_BOOTSTRAP_VAULT_NAME = "__bootstrap__"

_clients: dict[str, VaultClient] = {}
_init_lock = asyncio.Lock()


class VaultNotFoundError(Exception):
    """Levée quand un coffre nommé n'existe pas en DB (et pas de fallback bootstrap)."""


class InvalidVaultRefError(Exception):
    """Levée quand une chaîne ne matche pas le pattern `${vault://name:path}`."""


def parse_ref(value: str | None) -> tuple[str, str] | None:
    """Parse `${vault://<name>:<path>}` → `(name, path)`. None si pas un ref."""
    if not value:
        return None
    m = _VAULT_REF_RE.match(value)
    if not m:
        return None
    return m.group(1), m.group(2)


def build_ref(vault_name: str, path: str) -> str:
    """Construit le ref textuel `${vault://<name>:<path>}` à stocker en DB."""
    return f"${{vault://{vault_name}:{path}}}"


def _build_vault_client(token: str, base_url: str) -> VaultClient:
    """Instancie un `harpocrate.VaultClient`. Import local pour éviter le coût au boot."""
    from harpocrate import VaultClient

    return VaultClient(token=token, base_url=base_url)


async def _resolve_vault_credentials(vault_name: str | None) -> tuple[str, str, str]:
    """Retourne `(resolved_name, base_url, api_key)` pour le coffre demandé.

    - Si `vault_name` est fourni : lookup `harpocrate_vaults.name == vault_name`.
    - Si `vault_name` est None : lookup le coffre `is_default = true`.
    - Fallback bootstrap si AUCUN coffre en DB et `vault_name is None`:
      utilise `settings.harpocrate_{key,url}` (compat pré-multi-coffres).

    Lève `VaultNotFoundError` sinon.
    """
    from agflow.services import harpocrate_vaults_service

    if vault_name is None:
        default = await harpocrate_vaults_service.get_default()
        if default is not None:
            api_key = await harpocrate_vaults_service.reveal_api_key(default.id)
            return default.name, default.base_url, api_key
        # Bootstrap fallback : aucun coffre en DB.
        from agflow.config import get_settings

        settings = get_settings()
        if settings.harpocrate_key and settings.harpocrate_url:
            return _BOOTSTRAP_VAULT_NAME, settings.harpocrate_url, settings.harpocrate_key
        raise VaultNotFoundError(
            "No default Harpocrate vault configured (DB empty and HARPOCRATE_KEY/URL also unset)"
        )

    summary = await harpocrate_vaults_service.get_by_name(vault_name)
    if summary is None:
        raise VaultNotFoundError(f"Harpocrate vault '{vault_name}' not found")
    api_key = await harpocrate_vaults_service.reveal_api_key(summary.id)
    return summary.name, summary.base_url, api_key


async def _ensure_client(vault_name: str | None = None) -> tuple[str, VaultClient]:
    """Retourne `(resolved_name, client)` pour le coffre demandé, cache inclus."""
    async with _init_lock:
        # On résout d'abord le nom (peut être bootstrap si vault_name=None et DB vide),
        # puis on regarde le cache. Cela évite un cache miss / hit doublon entre
        # "default" et "<nom réel du coffre default>".
        resolved_name, base_url, api_key = await _resolve_vault_credentials(vault_name)
        client = _clients.get(resolved_name)
        if client is None:
            try:
                client = _build_vault_client(api_key, base_url)
            except Exception as exc:
                raise VaultNotFoundError(
                    f"Vault '{resolved_name}' has an invalid API key: {exc}"
                ) from exc
            _clients[resolved_name] = client
        return resolved_name, client


def reset_cache(vault_name: str | None = None) -> None:
    """Vide le cache d'un coffre précis, ou tout le cache si `vault_name is None`.

    À appeler après une rotation de clé (`update`) ou un `set_default`.
    """
    if vault_name is None:
        _clients.clear()
    else:
        _clients.pop(vault_name, None)


async def _run(fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(fn, *args, **kwargs))


async def get_secret(name: str, vault_name: str | None = None) -> str:
    """Lit et déchiffre la valeur d'un secret. Retry 1x sur 401."""
    from harpocrate.exceptions import VaultHttpError

    resolved_name, client = await _ensure_client(vault_name)
    try:
        return await _run(client.secrets.get, name)
    except VaultHttpError as exc:
        if exc.status_code == 401:
            _log.warning("vault_client.401_retry", vault=resolved_name, name=name)
            reset_cache(resolved_name)
            _, client = await _ensure_client(vault_name)
            return await _run(client.secrets.get, name)
        raise


async def resolve_ref(ref: str) -> str:
    """Lit la valeur pointée par un ref `${vault://<name>:<path>}`."""
    parsed = parse_ref(ref)
    if parsed is None:
        raise InvalidVaultRefError(f"Invalid vault ref: {ref!r}")
    vault_name, path = parsed
    return await get_secret(path, vault_name=vault_name)


async def list_secrets(limit: int = 200, vault_name: str | None = None) -> list:
    """Liste les secrets du wallet (sans valeurs)."""
    _, client = await _ensure_client(vault_name)
    resp = await _run(client.secrets.list_secrets, limit=limit)
    return resp.secrets


async def create_secret(
    name: str, value: str, description: str | None = None, vault_name: str | None = None,
) -> str:
    """Crée un nouveau secret dans le vault. Retourne le secret_id (UUID str)."""
    _, client = await _ensure_client(vault_name)
    return await _run(client.secrets.create, name, value, description)


async def update_secret(name: str, value: str, vault_name: str | None = None) -> None:
    """Met à jour la valeur d'un secret existant."""
    _, client = await _ensure_client(vault_name)
    await _run(client.secrets.put, name, value)


async def delete_secret(name: str, vault_name: str | None = None) -> None:
    """Supprime un secret du vault."""
    _, client = await _ensure_client(vault_name)
    await _run(client.secrets.delete, name)
