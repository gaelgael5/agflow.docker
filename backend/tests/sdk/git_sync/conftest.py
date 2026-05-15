"""Fixtures partagées pour les tests du SDK git_sync.

`bare_repo` matérialise un vrai repo Git bare local (file://) pour tester
clone/push/pull sans dépendance réseau. `fake_auth_provider` court-circuite
la résolution Harpocrate et le wiring auth — clone via file:// n'a pas
besoin de credentials.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sdk.git_sync.auth.base import GitAuthProvider


def _git(*args: str, cwd: Path | None = None) -> str:
    """Wrapper subprocess pour les fixtures (synchrone, lève si exit != 0)."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def bare_repo(tmp_path: Path) -> str:
    """Crée un repo bare local avec un commit initial sur `main`.

    Retourne l'URL `file://` du bare repo, utilisable avec `git clone`.
    Le repo contient un fichier `README.md` à la racine et le SDK doit
    pouvoir ajouter des fichiers sous `<module_name>/datas/`.
    """
    bare_path = tmp_path / "remote.git"
    seed_path = tmp_path / "seed"
    seed_path.mkdir()
    bare_path.mkdir()

    _git("init", "--bare", "--initial-branch=main", str(bare_path))
    _git("init", "--initial-branch=main", cwd=seed_path)
    _git("config", "user.email", "fixture@example.org", cwd=seed_path)
    _git("config", "user.name", "fixture", cwd=seed_path)
    (seed_path / "README.md").write_text("seed\n")
    _git("add", "README.md", cwd=seed_path)
    _git("commit", "-m", "initial", cwd=seed_path)
    _git("remote", "add", "origin", str(bare_path), cwd=seed_path)
    _git("push", "origin", "main", cwd=seed_path)

    return bare_path.as_uri()


class _PassthroughAuthProvider(GitAuthProvider):
    """Provider no-auth utilisé pour les tests sur file://."""

    def __init__(self) -> None:
        self.setup_called = 0
        self.teardown_called = 0

    def setup(self) -> None:
        self.setup_called += 1

    def teardown(self) -> None:
        self.teardown_called += 1

    def get_clone_url(self, repo_url: str) -> str:
        return repo_url

    def get_env(self) -> dict[str, str]:
        return {}


@pytest.fixture
def fake_auth_provider() -> _PassthroughAuthProvider:
    return _PassthroughAuthProvider()


@pytest.fixture
def fake_vault() -> AsyncMock:
    """Mock vault client compatible avec le contrat `async resolve()`."""
    vault = AsyncMock()
    vault.resolve = AsyncMock(return_value="dummy-secret")
    return vault
