"""Tests d'intégration du service `harpocrate_vaults_service`.

Ces tests touchent réellement la DB (chiffrement/déchiffrement pgcrypto inclus).
Ils sont sautés si la DB n'est pas accessible.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from agflow.schemas.harpocrate_vaults import (
    VaultCreateRequest,
    VaultUpdateRequest,
)
from agflow.services import harpocrate_vaults_service as vaults
from tests._db_reset import reset_schema_and_migrate

# Toutes les opérations chiffrement/déchiffrement nécessitent HARPOCRATE_DEK.
# On le force sur une valeur stable pour la session de tests.
_TEST_DEK = "test-dek-passphrase-very-long-and-stable-2026"
os.environ["HARPOCRATE_DEK"] = _TEST_DEK


@pytest.fixture
async def fresh_db() -> AsyncIterator[None]:
    await reset_schema_and_migrate()
    yield


def _payload(
    name: str = "default",
    base_url: str = "https://vault.example.com",
    api_key: str = "hrpv_1_test_token_value",
    api_key_id: str = "default",
    is_default: bool = False,
) -> VaultCreateRequest:
    return VaultCreateRequest(
        name=name,
        base_url=base_url,  # type: ignore[arg-type]
        api_key=api_key,
        api_key_id=api_key_id,
        is_default=is_default,
    )


@pytest.mark.asyncio
async def test_create_and_list_returns_summary_without_api_key(fresh_db: None) -> None:
    created = await vaults.create(_payload(name="default", api_key="hrpv_1_secret"))

    assert created.name == "default"
    assert created.is_default is False
    assert not hasattr(created, "api_key")

    items = await vaults.list_all()
    assert len(items) == 1
    assert items[0].id == created.id
    assert not hasattr(items[0], "api_key")


@pytest.mark.asyncio
async def test_reveal_api_key_round_trips_through_pgcrypto(fresh_db: None) -> None:
    secret = "hrpv_1_round_trip_secret_xyz123"
    created = await vaults.create(_payload(name="vault1", api_key=secret))

    revealed = await vaults.reveal_api_key(created.id)
    assert revealed == secret


@pytest.mark.asyncio
async def test_create_with_is_default_marks_it(fresh_db: None) -> None:
    created = await vaults.create(_payload(name="prod", is_default=True))
    assert created.is_default is True

    default = await vaults.get_default()
    assert default is not None
    assert default.id == created.id


@pytest.mark.asyncio
async def test_create_second_default_demotes_previous(fresh_db: None) -> None:
    v1 = await vaults.create(_payload(name="v1", is_default=True))
    v2 = await vaults.create(_payload(name="v2", is_default=True))

    refreshed_v1 = await vaults.get_by_id(v1.id)
    assert refreshed_v1.is_default is False
    assert v2.is_default is True


@pytest.mark.asyncio
async def test_create_rejects_duplicate_name(fresh_db: None) -> None:
    await vaults.create(_payload(name="duplicate"))
    with pytest.raises(vaults.DuplicateVaultNameError):
        await vaults.create(_payload(name="duplicate"))


@pytest.mark.asyncio
async def test_set_default_moves_flag_atomically(fresh_db: None) -> None:
    v1 = await vaults.create(_payload(name="v1", is_default=True))
    v2 = await vaults.create(_payload(name="v2"))

    promoted = await vaults.set_default(v2.id)
    assert promoted.is_default is True

    assert (await vaults.get_by_id(v1.id)).is_default is False
    assert (await vaults.get_by_id(v2.id)).is_default is True


@pytest.mark.asyncio
async def test_update_api_key_re_encrypts(fresh_db: None) -> None:
    created = await vaults.create(_payload(name="rotate", api_key="hrpv_1_old"))

    await vaults.update(
        created.id,
        VaultUpdateRequest(api_key="hrpv_1_new_token_after_rotation"),
    )

    revealed = await vaults.reveal_api_key(created.id)
    assert revealed == "hrpv_1_new_token_after_rotation"


@pytest.mark.asyncio
async def test_update_promotes_to_default(fresh_db: None) -> None:
    v1 = await vaults.create(_payload(name="v1", is_default=True))
    v2 = await vaults.create(_payload(name="v2"))

    updated = await vaults.update(v2.id, VaultUpdateRequest(is_default=True))
    assert updated.is_default is True
    assert (await vaults.get_by_id(v1.id)).is_default is False


@pytest.mark.asyncio
async def test_delete_removes_vault(fresh_db: None) -> None:
    created = await vaults.create(_payload(name="todelete"))
    await vaults.delete(created.id)

    with pytest.raises(vaults.VaultNotFoundError):
        await vaults.get_by_id(created.id)


@pytest.mark.asyncio
async def test_delete_missing_raises(fresh_db: None) -> None:
    import uuid

    with pytest.raises(vaults.VaultNotFoundError):
        await vaults.delete(uuid.uuid4())


@pytest.mark.asyncio
async def test_reveal_without_dek_raises(fresh_db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    created = await vaults.create(_payload(name="dektest"))

    # Force le settings à voir un DEK vide → reveal doit lever
    from agflow import config

    def _no_dek_settings() -> config.Settings:
        s = config.Settings()  # type: ignore[call-arg]
        s.harpocrate_dek = ""  # type: ignore[assignment]
        return s

    monkeypatch.setattr(config, "get_settings", _no_dek_settings)

    with pytest.raises(vaults.NoDekConfiguredError):
        await vaults.reveal_api_key(created.id)


@pytest.mark.asyncio
async def test_get_default_returns_none_when_no_vault(fresh_db: None) -> None:
    assert await vaults.get_default() is None
