"""Service stateless pour l'accès ad-hoc au vault Harpocrate.

Ce service ne lit pas la DB — il prend url + api_key directement en paramètre.
Utilisé par le wizard de restauration (étape 1 : connexion vault).
"""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

from harpocrate import VaultClient

from agflow.schemas.restore_wizard import VaultSecretItem


class InvalidVaultCredentialsError(Exception):
    """API key ou URL invalide."""


async def _run_sync(fn: Any, *args: Any, **kwargs: Any) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(fn, *args, **kwargs))


def _make_client(url: str, api_key: str) -> VaultClient:
    return VaultClient(token=api_key, base_url=url)


async def test_vault_connection(url: str, api_key: str) -> None:
    """Teste la connexion au vault. Lève InvalidVaultCredentialsError si invalide."""
    from harpocrate.exceptions import VaultHttpError

    client = _make_client(url, api_key)
    try:
        await _run_sync(client.secrets.list_secrets, limit=1)
    except VaultHttpError as exc:
        if exc.status_code == 401:
            raise InvalidVaultCredentialsError("API key invalide") from exc
        raise
    except Exception as exc:
        raise InvalidVaultCredentialsError(f"Vault injoignable : {exc}") from exc


# Empêche pytest de collecter cette fonction comme test (nom préfixé par "test_")
test_vault_connection.__test__ = False  # type: ignore[attr-defined]


async def list_vault_secrets_by_prefix(
    url: str, api_key: str, prefix: str
) -> list[VaultSecretItem]:
    """Liste les secrets du vault filtrés par préfixe de nom."""
    client = _make_client(url, api_key)
    resp = await _run_sync(client.secrets.list_secrets, limit=500)
    return [
        VaultSecretItem(
            name=s.name,
            tags=list(getattr(s, "tags", None) or []),
        )
        for s in resp.secrets
        if not prefix or s.name == prefix or s.name.startswith(prefix + "/")
    ]


async def get_vault_secret_value(url: str, api_key: str, name: str) -> str:
    """Lit la valeur déchiffrée d'un secret."""
    client = _make_client(url, api_key)
    return await _run_sync(client.secrets.get, name)
