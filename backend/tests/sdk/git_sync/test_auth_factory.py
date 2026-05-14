from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from sdk.git_sync.auth.basic_https import BasicHttpsAuthProvider
from sdk.git_sync.auth.factory import GitAuthProviderFactory
from sdk.git_sync.auth.pat_https import PATHttpsAuthProvider
from sdk.git_sync.auth.ssh_key import SSHKeyAuthProvider
from sdk.git_sync.exceptions import VaultResolutionError
from sdk.git_sync.models import AuthMode, GitConfig


def _cfg(mode: AuthMode, secret_ref: str) -> GitConfig:
    return GitConfig(
        repo_url="https://example.org/org/repo.git",
        auth_mode=mode,
        auth_secret_ref=secret_ref,
        module_name="docker",
        commit_author_name="bot",
        commit_author_email="bot@example.org",
    )


async def test_factory_builds_ssh_key_provider_from_vault_ref():
    vault = AsyncMock()
    vault.resolve = AsyncMock(return_value="-----PRIV KEY-----")
    config = _cfg(AuthMode.SSH_KEY, "${vault://git/docker/ssh_key}")

    provider = await GitAuthProviderFactory.build(config, vault)

    assert isinstance(provider, SSHKeyAuthProvider)
    vault.resolve.assert_awaited_once_with("${vault://git/docker/ssh_key}")


async def test_factory_builds_pat_https_provider():
    vault = AsyncMock()
    vault.resolve = AsyncMock(return_value="ghp_token123")
    config = _cfg(AuthMode.PAT_HTTPS, "${vault://git/docker/pat}")

    provider = await GitAuthProviderFactory.build(config, vault)

    assert isinstance(provider, PATHttpsAuthProvider)


async def test_factory_builds_basic_https_provider_with_json_secret():
    vault = AsyncMock()
    vault.resolve = AsyncMock(
        return_value='{"username": "alice", "password": "s3cr3t"}'
    )
    config = _cfg(AuthMode.BASIC_HTTPS, "${vault://git/docker/basic}")

    provider = await GitAuthProviderFactory.build(config, vault)

    assert isinstance(provider, BasicHttpsAuthProvider)
    # Vérification cross : la résolution a bien été déléguée
    injected = provider.get_clone_url("https://example.org/repo.git")
    assert "alice:s3cr3t@" in injected


async def test_factory_passes_resolved_secret_to_provider():
    """Le secret retourné par vault.resolve() doit être passé au provider.

    Couvre par extension le cas valeur littérale : c'est `VaultResolver.resolve`
    qui retourne la ref telle quelle quand elle n'est pas `${vault://...}` —
    la factory ne distingue pas les deux cas (testé ailleurs).
    """
    vault = AsyncMock()
    vault.resolve = AsyncMock(return_value="resolved-secret-value")
    config = _cfg(AuthMode.PAT_HTTPS, "${vault://any}")

    provider = await GitAuthProviderFactory.build(config, vault)

    assert isinstance(provider, PATHttpsAuthProvider)
    assert provider.get_clone_url("https://example.org/r.git") == (
        "https://resolved-secret-value@example.org/r.git"
    )


async def test_factory_propagates_vault_resolution_error():
    vault = AsyncMock()
    vault.resolve = AsyncMock(side_effect=VaultResolutionError("not found"))
    config = _cfg(AuthMode.SSH_KEY, "${vault://missing}")

    with pytest.raises(VaultResolutionError, match="not found"):
        await GitAuthProviderFactory.build(config, vault)
