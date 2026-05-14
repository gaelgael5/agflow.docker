from __future__ import annotations

import os
from pathlib import Path

import pytest

from sdk.git_sync.auth.base import GitAuthProvider
from sdk.git_sync.auth.basic_https import BasicHttpsAuthProvider
from sdk.git_sync.auth.pat_https import PATHttpsAuthProvider
from sdk.git_sync.auth.ssh_key import SSHKeyAuthProvider

# ─── ABC ─────────────────────────────────────────────────────────────────────


def test_git_auth_provider_is_abstract():
    """Instancier directement la classe abstraite doit échouer."""
    with pytest.raises(TypeError):
        GitAuthProvider()  # type: ignore[abstract]


# ─── SSHKeyAuthProvider ──────────────────────────────────────────────────────


def test_ssh_key_setup_writes_key_to_tempfile_and_teardown_removes_it():
    private_key = "-----BEGIN OPENSSH PRIVATE KEY-----\nfake-content\n-----END OPENSSH PRIVATE KEY-----\n"
    provider = SSHKeyAuthProvider(private_key)

    provider.setup()
    try:
        assert provider.key_path is not None
        key_path = Path(provider.key_path)
        assert key_path.exists()
        assert key_path.read_text() == private_key
    finally:
        provider.teardown()

    assert not Path(key_path).exists()
    # Après teardown, key_path est remis à None pour signaler l'état propre
    assert provider.key_path is None


def test_ssh_key_get_env_returns_git_ssh_command_with_key_path():
    provider = SSHKeyAuthProvider("dummy-key")
    provider.setup()
    try:
        env = provider.get_env()
        assert "GIT_SSH_COMMAND" in env
        cmd = env["GIT_SSH_COMMAND"]
        assert "-i" in cmd
        assert provider.key_path in cmd
        assert "StrictHostKeyChecking=no" in cmd
    finally:
        provider.teardown()


def test_ssh_key_get_clone_url_returns_url_unchanged():
    provider = SSHKeyAuthProvider("dummy-key")
    url = "git@github.com:org/repo.git"
    assert provider.get_clone_url(url) == url


def test_ssh_key_get_env_before_setup_raises():
    """L'appelant doit setup() d'abord — get_env() sans setup est une erreur."""
    provider = SSHKeyAuthProvider("dummy-key")
    with pytest.raises(RuntimeError, match="setup"):
        provider.get_env()


def test_ssh_key_teardown_idempotent():
    """Appeler teardown() plusieurs fois (ou sans setup) ne doit pas exploser."""
    provider = SSHKeyAuthProvider("dummy-key")
    provider.teardown()  # avant setup → no-op
    provider.setup()
    provider.teardown()
    provider.teardown()  # second teardown après setup → no-op


def test_ssh_key_file_permissions_when_supported():
    """Sur Linux/Mac, le fichier doit être chmod 600. Sur Windows on tolère."""
    provider = SSHKeyAuthProvider("k")
    provider.setup()
    try:
        if os.name == "posix":
            mode = os.stat(provider.key_path).st_mode & 0o777
            assert mode == 0o600
    finally:
        provider.teardown()


# ─── PATHttpsAuthProvider ────────────────────────────────────────────────────


def test_pat_injects_token_into_https_url():
    provider = PATHttpsAuthProvider("ghp_abc123")
    url = "https://github.com/org/repo.git"
    assert provider.get_clone_url(url) == "https://ghp_abc123@github.com/org/repo.git"


def test_pat_replaces_existing_credentials_in_url():
    provider = PATHttpsAuthProvider("ghp_new")
    url = "https://old-user:old-pass@github.com/org/repo.git"
    assert provider.get_clone_url(url) == "https://ghp_new@github.com/org/repo.git"


def test_pat_preserves_port_in_url():
    provider = PATHttpsAuthProvider("tok")
    url = "https://gitea.local:3000/org/repo.git"
    assert provider.get_clone_url(url) == "https://tok@gitea.local:3000/org/repo.git"


def test_pat_preserves_path_and_query():
    provider = PATHttpsAuthProvider("tok")
    url = "https://git.example.org/group/subgroup/repo.git?ref=main"
    assert provider.get_clone_url(url) == (
        "https://tok@git.example.org/group/subgroup/repo.git?ref=main"
    )


def test_pat_get_env_empty_and_setup_teardown_noop():
    provider = PATHttpsAuthProvider("tok")
    provider.setup()  # no-op, doit pas lancer
    assert provider.get_env() == {}
    provider.teardown()  # no-op


# ─── BasicHttpsAuthProvider ──────────────────────────────────────────────────


def test_basic_https_parses_json_and_injects_credentials():
    provider = BasicHttpsAuthProvider('{"username": "alice", "password": "s3cr3t"}')
    url = "https://gitea.example.org/org/repo.git"
    assert provider.get_clone_url(url) == "https://alice:s3cr3t@gitea.example.org/org/repo.git"


def test_basic_https_invalid_json_raises_on_construction():
    with pytest.raises(ValueError, match="JSON"):
        BasicHttpsAuthProvider("not-json")


def test_basic_https_missing_username_or_password_raises():
    with pytest.raises(ValueError, match=r"username|password"):
        BasicHttpsAuthProvider('{"username": "alice"}')
    with pytest.raises(ValueError, match=r"username|password"):
        BasicHttpsAuthProvider('{"password": "x"}')


def test_basic_https_replaces_existing_credentials():
    provider = BasicHttpsAuthProvider('{"username": "alice", "password": "s3cr3t"}')
    url = "https://old:cred@gitea.example.org/repo.git"
    assert provider.get_clone_url(url) == "https://alice:s3cr3t@gitea.example.org/repo.git"


def test_basic_https_get_env_empty():
    provider = BasicHttpsAuthProvider('{"username": "u", "password": "p"}')
    assert provider.get_env() == {}
