"""Wrapper async autour des commandes Git CLI via subprocess.

Pattern d'usage imposé (spec §6) :

    repo_root = None
    try:
        repo_root = await git_service.clone()
        # ... travail ...
        sha = await git_service.commit_and_push(repo_root, message)
    finally:
        if repo_root:
            git_service.cleanup(repo_root)

`cleanup()` est sync (pas d'I/O réseau, juste rmtree + provider.teardown)
mais il DOIT être appelé dans le finally pour ne pas fuiter de fichiers
temporaires (clé SSH, repo clone).
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Protocol

from sdk.git_sync.auth.base import GitAuthProvider
from sdk.git_sync.auth.factory import GitAuthProviderFactory
from sdk.git_sync.exceptions import (
    GitCloneError,
    GitConflictError,
    GitPushError,
)
from sdk.git_sync.models import GitConfig


class _VaultClientProtocol(Protocol):
    async def resolve(self, ref: str) -> str: ...


class GitService:
    def __init__(self, config: GitConfig, vault_client: _VaultClientProtocol) -> None:
        self._config = config
        self._vault = vault_client
        self._auth_provider: GitAuthProvider | None = None

    # ─── Opérations publiques ────────────────────────────────────────────

    async def clone(self) -> Path:
        """Clone le repo dans un répertoire temporaire et retourne son path.

        Réalise la résolution du secret (auth lazy), instancie le provider,
        l'expose à Git via `GIT_SSH_COMMAND` / URL injection, et fait
        `git clone --branch <branch> --depth 1`. Si `config.target_commit`
        est défini, fait un `git checkout` dessus juste après.
        """
        self._auth_provider = await GitAuthProviderFactory.build(
            self._config, self._vault
        )
        self._auth_provider.setup()

        tmp_dir = Path(tempfile.mkdtemp(prefix="git_sync_"))
        clone_url = self._auth_provider.get_clone_url(self._config.repo_url)
        env = {**os.environ, **self._auth_provider.get_env()}

        rc, _, stderr = await _run_git(
            [
                "clone",
                "--branch",
                self._config.branch,
                "--depth",
                "1",
                clone_url,
                str(tmp_dir),
            ],
            env=env,
        )
        if rc != 0:
            # Nettoyage avant de lever pour ne pas laisser un tmp_dir orphelin.
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise GitCloneError(
                f"git clone a échoué (exit {rc}) sur {self._config.repo_url}: "
                f"{stderr.strip()}"
            )

        if self._config.target_commit:
            # `--depth 1` ne descend qu'un commit ; pour pouvoir checkout un
            # SHA arbitraire, il faut un fetch unshallow.
            await _run_git(
                ["-C", str(tmp_dir), "fetch", "--unshallow"], env=env
            )
            rc, _, stderr = await _run_git(
                [
                    "-C",
                    str(tmp_dir),
                    "checkout",
                    self._config.target_commit,
                ],
                env=env,
            )
            if rc != 0:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                raise GitCloneError(
                    f"checkout {self._config.target_commit!r} a échoué : "
                    f"{stderr.strip()}"
                )

        return tmp_dir

    def get_module_path(self, repo_root: Path) -> Path:
        """Path du sous-répertoire datas du module dans le repo cloné.

        Crée les répertoires intermédiaires si absents : `mkdir -p`.
        """
        path = repo_root / self._config.module_name / "datas"
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def pull_ff_only(self, repo_root: Path) -> None:
        """`git pull --ff-only`. Lance GitConflictError si non-ff."""
        env = self._git_env()
        rc, _, stderr = await _run_git(
            ["-C", str(repo_root), "pull", "--ff-only"], env=env
        )
        if rc != 0:
            raise GitConflictError(
                "Le repo a été modifié depuis le dernier export. "
                "Exportez à nouveau ou résolvez manuellement. "
                f"(git stderr: {stderr.strip()})"
            )

    async def commit_and_push(
        self, repo_root: Path, message: str
    ) -> str | None:
        """Stage le module_path, commit + push. Retourne le SHA ou None.

        Si `git diff --cached --quiet` indique qu'il n'y a rien à committer
        (exit 0), retourne `None` sans erreur. Sinon commit + push et
        retourne le SHA de HEAD. Lance `GitPushError` si le push échoue.
        """
        env = self._git_env()

        # Configure l'identité du commit côté repo cloné (pas global).
        await _run_git(
            [
                "-C",
                str(repo_root),
                "config",
                "user.name",
                self._config.commit_author_name,
            ],
            env=env,
        )
        await _run_git(
            [
                "-C",
                str(repo_root),
                "config",
                "user.email",
                self._config.commit_author_email,
            ],
            env=env,
        )

        module_path = self.get_module_path(repo_root)
        await _run_git(
            ["-C", str(repo_root), "add", str(module_path)], env=env
        )

        # `git diff --cached --quiet` retourne 0 si pas de diff, 1 si diff.
        rc, _, _ = await _run_git(
            ["-C", str(repo_root), "diff", "--cached", "--quiet"], env=env
        )
        if rc == 0:
            return None  # rien à committer

        rc, _, stderr = await _run_git(
            ["-C", str(repo_root), "commit", "-m", message], env=env
        )
        if rc != 0:
            raise GitPushError(
                f"git commit a échoué (exit {rc}) : {stderr.strip()}"
            )

        rc, _, stderr = await _run_git(
            [
                "-C",
                str(repo_root),
                "push",
                "origin",
                self._config.branch,
            ],
            env=env,
        )
        if rc != 0:
            raise GitPushError(
                f"git push a échoué (exit {rc}) sur {self._config.branch}: "
                f"{stderr.strip()}"
            )

        rc, stdout, stderr = await _run_git(
            ["-C", str(repo_root), "rev-parse", "HEAD"], env=env
        )
        if rc != 0:
            raise GitPushError(f"rev-parse HEAD a échoué : {stderr.strip()}")
        return stdout.strip()

    def cleanup(self, repo_root: Path) -> None:
        """Supprime le répertoire de travail + teardown du provider.

        Idempotent : tolère un repo_root déjà absent et un auth_provider
        jamais initialisé. À TOUJOURS appeler dans un `finally`.

        Sur Windows, les objets dans `.git/objects/` sont créés en
        read-only ; un `rmtree` standard échoue silencieusement avec
        ignore_errors=True. On installe un handler qui force write+retry.
        """
        shutil.rmtree(repo_root, onexc=_force_remove_readonly)
        if self._auth_provider is not None:
            self._auth_provider.teardown()
            self._auth_provider = None

    # ─── Helpers internes ────────────────────────────────────────────────

    def _git_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self._auth_provider is not None:
            env.update(self._auth_provider.get_env())
        return env


def _force_remove_readonly(func, path, exc):
    """Handler `shutil.rmtree(onexc=...)` qui rend writable + retry.

    Tolère le cas « path déjà absent » (FileNotFoundError) pour rester
    idempotent. Toute autre erreur post-chmod est suppressée — on est
    dans un cleanup, on ne veut pas masquer une exception en cours.
    """
    import stat

    if isinstance(exc, FileNotFoundError):
        return
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


async def _run_git(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Exécute `git <args>` et retourne `(rc, stdout, stderr)` décodés.

    Volontairement sans `check=True` : chaque appelant décide quelle
    exception spécifique du SDK lever en fonction du contexte (clone,
    conflict, push).
    """
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return (
        proc.returncode if proc.returncode is not None else -1,
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
    )
