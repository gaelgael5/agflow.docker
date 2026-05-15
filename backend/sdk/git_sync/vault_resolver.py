"""Résolution des références `${vault://path}` via un client Harpocrate.

Le SDK Git Sync attend, dans `GitConfig.auth_secret_ref`, soit :
  - une référence `${vault://<path>}` qui est résolue lazy au premier accès
  - une valeur littérale (mode dev/test uniquement — jamais en prod)

Ce module fournit un wrapper asynchrone autour d'un client `harpocrate.SecretsClient`
(sync) qui :
  1. distingue les deux cas via `is_vault_ref()`
  2. délègue à `client.get(path)` dans un thread pour ne pas bloquer la
     boucle asyncio pendant l'appel HTTP

L'interface attendue du client (duck-typing) :
  ``def get(self, name: str) -> str``
"""
from __future__ import annotations

import asyncio
from typing import Any

from sdk.git_sync.exceptions import VaultResolutionError

_VAULT_PREFIX = "${vault://"
_VAULT_SUFFIX = "}"


def is_vault_ref(value: str) -> bool:
    """Retourne True si `value` a la forme syntaxique `${vault://...}`.

    Ne valide pas que le path soit non-vide — ça reste à `VaultResolver.resolve`
    qui lance VaultResolutionError dans ce cas.
    """
    return value.startswith(_VAULT_PREFIX) and value.endswith(_VAULT_SUFFIX)


class VaultResolver:
    """Adaptateur sync→async autour d'un client Harpocrate.

    Le client passé en constructeur doit exposer `get(name: str) -> str`.
    Toute autre forme d'erreur (réseau, secret introuvable, permission)
    est enveloppée dans `VaultResolutionError` pour ne pas faire fuiter
    le type concret du client dans l'API publique du SDK.
    """

    def __init__(self, secrets_client: Any) -> None:
        self._client = secrets_client

    async def resolve(self, ref: str) -> str:
        """Résout une référence vault ou retourne la valeur littérale.

        - `${vault://path}` → `await asyncio.to_thread(client.get, path)`
        - autre              → retourne `ref` inchangée (mode dev/test)
        """
        if not is_vault_ref(ref):
            return ref

        path = ref[len(_VAULT_PREFIX) : -len(_VAULT_SUFFIX)]
        if not path:
            raise VaultResolutionError(
                f"référence vault invalide : path vide dans {ref!r}"
            )

        try:
            return await asyncio.to_thread(self._client.get, path)
        except VaultResolutionError:
            raise
        except Exception as exc:
            raise VaultResolutionError(
                f"échec de résolution de {ref!r} : {exc}"
            ) from exc
