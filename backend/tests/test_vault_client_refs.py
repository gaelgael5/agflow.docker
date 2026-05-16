"""Tests purs des helpers parse_ref / build_ref / resolve_ref de vault_client."""
from __future__ import annotations

import pytest

from agflow.services import vault_client


def test_build_ref_format() -> None:
    ref = vault_client.build_ref("default", "certificates/abc/private_key")
    assert ref == "${vault://default:certificates/abc/private_key}"


def test_parse_ref_extracts_name_and_path() -> None:
    parsed = vault_client.parse_ref("${vault://prod-secrets:machines/uuid/password}")
    assert parsed == ("prod-secrets", "machines/uuid/password")


def test_parse_ref_round_trips_through_build() -> None:
    original = vault_client.build_ref("my-vault", "foo/bar/baz")
    assert vault_client.parse_ref(original) == ("my-vault", "foo/bar/baz")


def test_parse_ref_returns_none_for_invalid_inputs() -> None:
    assert vault_client.parse_ref(None) is None
    assert vault_client.parse_ref("") is None
    assert vault_client.parse_ref("plain-string") is None
    assert vault_client.parse_ref("${vault://}") is None
    assert vault_client.parse_ref("${vault://only-name-no-colon}") is None


def test_parse_ref_accepts_any_vault_name() -> None:
    # Plus de constante hardcodée : tout nom est accepté tant qu'il ne
    # contient pas le séparateur `:` (qui marque la fin du nom).
    assert vault_client.parse_ref("${vault://VAULT_42:p}") == ("VAULT_42", "p")
    assert vault_client.parse_ref("${vault://with-dashes:p}") == ("with-dashes", "p")


@pytest.mark.asyncio
async def test_resolve_ref_routes_to_named_vault(vault_mock) -> None:
    # vault_mock store ignore le vault_name (mock unique), mais on vérifie
    # que resolve_ref accepte un ref bien formé et délègue à get_secret(path).
    vault_mock.create("certificates/abc/private_key", "PEM-DATA")

    val = await vault_client.resolve_ref(
        "${vault://default:certificates/abc/private_key}",
    )
    assert val == "PEM-DATA"


@pytest.mark.asyncio
async def test_resolve_ref_raises_on_invalid_format(vault_mock) -> None:
    with pytest.raises(vault_client.InvalidVaultRefError):
        await vault_client.resolve_ref("not-a-ref")
