"""Mock in-memory du module `agflow.services.vault_client`.

Permet d'exécuter les tests qui dépendent de Harpocrate sans coffre réel.
Les fonctions monkey-patchées préservent la même signature et lèvent les
mêmes exceptions (`harpocrate.exceptions.SecretNotFound`, `VaultHttpError`)
que l'implémentation réelle, pour que le code applicatif sous test ne voie
aucune différence.

Usage type (function-scope, déjà nettoyé entre tests) :

    from tests._vault_mock import vault_mock

    @pytest.mark.asyncio
    async def test_xxx(vault_mock) -> None:
        # le store démarre vide ; toute écriture est isolée à ce test
        await secrets_service.create("KEY", "value")
        ...
"""
from __future__ import annotations

from uuid import uuid4

import pytest


class _Store:
    """Backing in-memory de l'API Harpocrate. Un store par test."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, object]] = {}

    def get(self, name: str) -> str:
        from harpocrate.exceptions import SecretNotFound

        entry = self._data.get(name)
        if entry is None:
            raise SecretNotFound(f"Secret '{name}' not found")
        return str(entry["value"])

    def list(self) -> list:
        from harpocrate.models.secret import SecretInfo

        return [
            SecretInfo(
                id=entry["id"],  # type: ignore[arg-type]
                name=name,
                description=entry.get("description"),  # type: ignore[arg-type]
                tags=list(entry.get("tags", [])),  # type: ignore[arg-type]
                is_placeholder=bool(entry.get("is_placeholder", False)),
                generation_version=1,
            )
            for name, entry in self._data.items()
        ]

    def create(self, name: str, value: str, description: str | None = None) -> str:
        from harpocrate.exceptions import VaultHttpError

        if name in self._data:
            raise VaultHttpError(409, {"detail": f"secret {name} already exists"})
        sid = str(uuid4())
        self._data[name] = {
            "id": __import__("uuid").UUID(sid),
            "value": value,
            "description": description,
            "tags": [],
            "is_placeholder": False,
        }
        return sid

    def update(self, name: str, value: str) -> None:
        from harpocrate.exceptions import SecretNotFound

        entry = self._data.get(name)
        if entry is None:
            raise SecretNotFound(f"Secret '{name}' not found")
        entry["value"] = value

    def delete(self, name: str) -> None:
        from harpocrate.exceptions import SecretNotFound

        if name not in self._data:
            raise SecretNotFound(f"Secret '{name}' not found")
        del self._data[name]


@pytest.fixture
def vault_mock(monkeypatch: pytest.MonkeyPatch) -> _Store:
    """Patch `agflow.services.vault_client.*` pour utiliser un store en mémoire.

    Tous les `await vault_client.xxx(...)` du code sous test sont redirigés
    vers ce store. Lève les mêmes exceptions que l'implémentation réelle.
    """
    from agflow.services import vault_client

    store = _Store()

    async def _get_secret(name: str, vault_name: str | None = None) -> str:
        return store.get(name)

    async def _list_secrets(limit: int = 200, vault_name: str | None = None) -> list:
        return store.list()[:limit]

    async def _create_secret(
        name: str,
        value: str,
        description: str | None = None,
        vault_name: str | None = None,
    ) -> str:
        return store.create(name, value, description)

    async def _update_secret(
        name: str, value: str, vault_name: str | None = None,
    ) -> None:
        store.update(name, value)

    async def _delete_secret(name: str, vault_name: str | None = None) -> None:
        store.delete(name)

    async def _resolve_ref(ref: str) -> str:
        parsed = vault_client.parse_ref(ref)
        if parsed is None:
            raise vault_client.InvalidVaultRefError(f"Invalid vault ref: {ref!r}")
        _vault_name, path = parsed
        return store.get(path)

    monkeypatch.setattr(vault_client, "get_secret", _get_secret)
    monkeypatch.setattr(vault_client, "list_secrets", _list_secrets)
    monkeypatch.setattr(vault_client, "create_secret", _create_secret)
    monkeypatch.setattr(vault_client, "update_secret", _update_secret)
    monkeypatch.setattr(vault_client, "delete_secret", _delete_secret)
    monkeypatch.setattr(vault_client, "resolve_ref", _resolve_ref)

    # Patche le builder bas-niveau et vide le cache de clients : si un autre
    # code de l'app (ex: bootstrap, vérif de santé) tente d'instancier le
    # VaultClient réel via _build_vault_client, on retourne un objet sentinel
    # plutôt que de laisser harpocrate lever InvalidTokenError sur le token
    # "dummy" du .env de test. Les méthodes du sentinel ne doivent jamais
    # être appelées (toute la surface I/O passe par les fonctions patchées
    # ci-dessus).
    class _SentinelClient:
        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            raise AssertionError(
                f"VaultClient.{name} appelé alors que vault_mock est actif — "
                "monkeypatch incomplet, mocker la fonction concrète "
                "dans tests/_vault_mock.py"
            )

    monkeypatch.setattr(
        vault_client, "_build_vault_client", lambda *_a, **_k: _SentinelClient(),
    )
    vault_client._clients.clear()

    return store
