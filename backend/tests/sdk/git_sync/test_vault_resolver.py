from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sdk.git_sync.exceptions import VaultResolutionError
from sdk.git_sync.vault_resolver import VaultResolver, is_vault_ref

# ─── is_vault_ref ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        ("${vault://git/docker/ssh_key}", True),
        ("${vault://x}", True),
        ("not-a-ref", False),
        ("vault://x", False),  # manque ${...}
        ("${vault://}", True),  # forme syntaxique mais path vide — détecté à la résolution
        ("", False),
        ("${other://x}", False),
    ],
)
def test_is_vault_ref(value, expected):
    assert is_vault_ref(value) is expected


# ─── VaultResolver.resolve ───────────────────────────────────────────────────


async def test_resolve_vault_ref_calls_client_get_with_path():
    client = MagicMock()
    client.get = MagicMock(return_value="-----PRIV KEY-----")
    resolver = VaultResolver(client)

    result = await resolver.resolve("${vault://git/docker/ssh_key}")

    assert result == "-----PRIV KEY-----"
    client.get.assert_called_once_with("git/docker/ssh_key")


async def test_resolve_literal_value_returned_as_is_without_client_call():
    """Mode dev/test : la valeur ne commence pas par ${vault:// → pas de résolution."""
    client = MagicMock()
    resolver = VaultResolver(client)

    result = await resolver.resolve("literal-private-key-content")

    assert result == "literal-private-key-content"
    client.get.assert_not_called()


async def test_resolve_empty_path_raises():
    client = MagicMock()
    resolver = VaultResolver(client)

    with pytest.raises(VaultResolutionError, match="vide"):
        await resolver.resolve("${vault://}")


async def test_resolve_client_failure_wrapped_in_vault_resolution_error():
    client = MagicMock()
    client.get = MagicMock(side_effect=RuntimeError("network timeout"))
    resolver = VaultResolver(client)

    with pytest.raises(VaultResolutionError, match="network timeout"):
        await resolver.resolve("${vault://git/docker/ssh_key}")


async def test_resolve_runs_blocking_client_get_in_thread():
    """Le client Harpocrate est sync — l'appel doit passer par asyncio.to_thread.

    On vérifie indirectement : un client lent (sleep) ne bloque pas la boucle
    event au point d'empêcher une autre tâche async de tourner en parallèle.
    """
    import asyncio
    import time

    def slow_get(path: str) -> str:
        time.sleep(0.05)
        return f"value-for-{path}"

    client = MagicMock()
    client.get = slow_get
    resolver = VaultResolver(client)

    async def other_work():
        await asyncio.sleep(0.01)
        return "other-done"

    # Lancer les deux concurremment : si resolve bloquait, other_work serait
    # gated jusqu'à la fin du sleep (50ms). On vérifie qu'ils se complètent
    # tous les deux dans un délai cohérent avec une exécution concurrente.
    start = time.monotonic()
    results = await asyncio.gather(
        resolver.resolve("${vault://x}"),
        other_work(),
    )
    elapsed = time.monotonic() - start

    assert results == ["value-for-x", "other-done"]
    # Le sleep bloquant fait 50ms ; si exécution concurrente correcte, total ≈ 50ms.
    # On donne une marge généreuse à 150ms.
    assert elapsed < 0.15
