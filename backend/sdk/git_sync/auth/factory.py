"""Construction du provider d'authentification depuis une `GitConfig`.

Délègue la résolution du secret (ref vault ou valeur littérale) à un
client `vault_client` qui doit exposer `async resolve(ref: str) -> str`
(typiquement : `sdk.git_sync.vault_resolver.VaultResolver`).
"""
from __future__ import annotations

from typing import Protocol

from sdk.git_sync.auth.base import GitAuthProvider
from sdk.git_sync.auth.basic_https import BasicHttpsAuthProvider
from sdk.git_sync.auth.pat_https import PATHttpsAuthProvider
from sdk.git_sync.auth.ssh_key import SSHKeyAuthProvider
from sdk.git_sync.models import AuthMode, GitConfig


class _VaultClientProtocol(Protocol):
    """Contrat structurel attendu du client vault — duck-typed."""

    async def resolve(self, ref: str) -> str: ...


class GitAuthProviderFactory:
    """Factory stateless. Instanciée jamais — uniquement `await build(...)`."""

    @staticmethod
    async def build(
        config: GitConfig, vault_client: _VaultClientProtocol
    ) -> GitAuthProvider:
        secret = await vault_client.resolve(config.auth_secret_ref)

        if config.auth_mode == AuthMode.SSH_KEY:
            return SSHKeyAuthProvider(secret)
        if config.auth_mode == AuthMode.PAT_HTTPS:
            return PATHttpsAuthProvider(secret)
        if config.auth_mode == AuthMode.BASIC_HTTPS:
            return BasicHttpsAuthProvider(secret)

        raise ValueError(f"AuthMode non supporté : {config.auth_mode!r}")
