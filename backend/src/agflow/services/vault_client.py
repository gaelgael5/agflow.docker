"""Async wrapper singleton autour du SDK Harpocrate synchrone.

Expose les opérations CRUD sur les secrets du vault via run_in_executor.
Gère un retry automatique sur 401 (token révoqué) en réinitialisant le client.
"""
from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from harpocrate import VaultClient

_log = structlog.get_logger(__name__)
_client: VaultClient | None = None
_init_lock = asyncio.Lock()


def _build_client() -> VaultClient:
    from harpocrate import VaultClient

    from agflow.config import get_settings

    settings = get_settings()
    if not settings.harpocrate_key:
        raise RuntimeError("HARPOCRATE_KEY not configured")
    if not settings.harpocrate_url:
        raise RuntimeError("HARPOCRATE_URL not configured")
    return VaultClient(token=settings.harpocrate_key, base_url=settings.harpocrate_url)


def _sync_client() -> VaultClient:
    global _client
    if _client is None:
        _client = _build_client()
    return _client


def _reset_client() -> None:
    global _client
    _client = None


async def _run(fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(fn, *args, **kwargs))


async def get_secret(name: str) -> str:
    """Lit et déchiffre la valeur d'un secret. Retry 1x sur 401."""
    from harpocrate.exceptions import VaultHttpError

    client = _sync_client()
    try:
        return await _run(client.secrets.get, name)
    except VaultHttpError as exc:
        if exc.status_code == 401:
            _log.warning("vault_client.401_retry", name=name)
            _reset_client()
            client = _sync_client()
            return await _run(client.secrets.get, name)
        raise


async def list_secrets(limit: int = 200) -> list:
    """Liste les secrets du wallet (sans valeurs). Retourne list[SecretInfo]."""
    client = _sync_client()
    resp = await _run(client.secrets.list_secrets, limit=limit)
    return resp.secrets


async def create_secret(name: str, value: str, description: str | None = None) -> str:
    """Crée un nouveau secret dans le vault. Retourne le secret_id (UUID str)."""
    client = _sync_client()
    return await _run(client.secrets.create, name, value, description)


async def update_secret(name: str, value: str) -> None:
    """Met à jour la valeur d'un secret existant."""
    client = _sync_client()
    await _run(client.secrets.put, name, value)


async def delete_secret(name: str) -> None:
    """Supprime un secret du vault."""
    client = _sync_client()
    await _run(client.secrets.delete, name)
