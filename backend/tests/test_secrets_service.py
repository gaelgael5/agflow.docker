"""Tests unitaires de `agflow.services.secrets_service`.

Le service délègue à `vault_client` (qui appelle Harpocrate). Les tests
utilisent la fixture `vault_mock` (cf. `tests/_vault_mock.py`) qui patch
toutes les fonctions de `vault_client` pour stocker en mémoire, sans
dépendance à un coffre réel.
"""
from __future__ import annotations

import pytest

from agflow.services import secrets_service
from tests._vault_mock import vault_mock  # noqa: F401  — fixture utilisée par injection


@pytest.mark.asyncio
async def test_create_secret(vault_mock) -> None:
    summary = await secrets_service.create("ANTHROPIC_API_KEY", "sk-ant-xyz")

    assert summary.name == "ANTHROPIC_API_KEY"
    # Le secret est bien dans le store mocké
    assert vault_mock.get("ANTHROPIC_API_KEY") == "sk-ant-xyz"


@pytest.mark.asyncio
async def test_reveal_returns_value(vault_mock) -> None:
    await secrets_service.create("OPENAI_API_KEY", "sk-openai-abc")

    revealed = await secrets_service.reveal("OPENAI_API_KEY")
    assert revealed.name == "OPENAI_API_KEY"
    assert revealed.value == "sk-openai-abc"


@pytest.mark.asyncio
async def test_list_returns_summaries_without_values(vault_mock) -> None:
    await secrets_service.create("KEY_A", "value-a")
    await secrets_service.create("KEY_B", "value-b")

    items = await secrets_service.list_all()
    names = [s.name for s in items]
    assert "KEY_A" in names
    assert "KEY_B" in names

    # Les summaries ne doivent pas exposer la valeur
    for item in items:
        assert not hasattr(item, "value")


@pytest.mark.asyncio
async def test_update_replaces_value(vault_mock) -> None:
    await secrets_service.create("KEY_UPDATE", "old")

    await secrets_service.update("KEY_UPDATE", "new")

    revealed = await secrets_service.reveal("KEY_UPDATE")
    assert revealed.value == "new"


@pytest.mark.asyncio
async def test_delete_removes_the_secret(vault_mock) -> None:
    await secrets_service.create("KEY_DEL", "x")

    await secrets_service.delete("KEY_DEL")

    items = await secrets_service.list_all()
    assert all(s.name != "KEY_DEL" for s in items)


@pytest.mark.asyncio
async def test_create_rejects_duplicate_name(vault_mock) -> None:
    await secrets_service.create("DUPKEY", "a")

    with pytest.raises(secrets_service.DuplicateSecretError):
        await secrets_service.create("DUPKEY", "b")


@pytest.mark.asyncio
async def test_reveal_missing_raises(vault_mock) -> None:
    with pytest.raises(secrets_service.SecretNotFoundError):
        await secrets_service.reveal("DOES_NOT_EXIST")


@pytest.mark.asyncio
async def test_update_missing_raises(vault_mock) -> None:
    with pytest.raises(secrets_service.SecretNotFoundError):
        await secrets_service.update("DOES_NOT_EXIST", "value")


@pytest.mark.asyncio
async def test_delete_missing_raises(vault_mock) -> None:
    with pytest.raises(secrets_service.SecretNotFoundError):
        await secrets_service.delete("DOES_NOT_EXIST")


@pytest.mark.asyncio
async def test_resolve_env_returns_dict(vault_mock) -> None:
    await secrets_service.create("ANTHROPIC_API_KEY", "sk-ant")
    await secrets_service.create("OPENAI_API_KEY", "sk-openai")

    env = await secrets_service.resolve_env(
        ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
    )
    assert env == {"ANTHROPIC_API_KEY": "sk-ant", "OPENAI_API_KEY": "sk-openai"}


@pytest.mark.asyncio
async def test_resolve_env_raises_on_missing(vault_mock) -> None:
    with pytest.raises(secrets_service.SecretNotFoundError) as exc:
        await secrets_service.resolve_env(["MISSING_KEY"])
    assert "MISSING_KEY" in str(exc.value)


@pytest.mark.asyncio
async def test_resolve_status_returns_per_var(vault_mock) -> None:
    await secrets_service.create("KEY_OK", "value")
    await secrets_service.create("KEY_EMPTY", " ")

    status = await secrets_service.resolve_status(
        ["KEY_OK", "KEY_EMPTY", "KEY_MISSING"]
    )
    assert status["KEY_OK"] == "ok"
    assert status["KEY_EMPTY"] == "empty"
    assert status["KEY_MISSING"] == "missing"
