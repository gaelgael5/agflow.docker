"""Couche d'authentification Git du SDK.

Trois modes supportés (SSH, PAT HTTPS, Basic HTTPS), pilotés par
`GitAuthProviderFactory.build(config, vault_client)`. Chaque provider
expose un cycle `setup() / get_clone_url() / get_env() / teardown()`
qui DOIT être utilisé via try/finally pour garantir le nettoyage.
"""
from __future__ import annotations

from sdk.git_sync.auth.base import GitAuthProvider
from sdk.git_sync.auth.basic_https import BasicHttpsAuthProvider
from sdk.git_sync.auth.factory import GitAuthProviderFactory
from sdk.git_sync.auth.pat_https import PATHttpsAuthProvider
from sdk.git_sync.auth.ssh_key import SSHKeyAuthProvider

__all__ = [
    "BasicHttpsAuthProvider",
    "GitAuthProvider",
    "GitAuthProviderFactory",
    "PATHttpsAuthProvider",
    "SSHKeyAuthProvider",
]
