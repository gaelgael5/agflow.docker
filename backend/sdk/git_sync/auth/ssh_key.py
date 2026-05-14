"""Provider Git basé sur une clé privée SSH.

La clé est matérialisée dans un fichier temporaire chmod 600 le temps
de l'opération Git, puis supprimée dans `teardown()`. Le path du fichier
n'est jamais loggué — il transite uniquement via `GIT_SSH_COMMAND`.
"""
from __future__ import annotations

import os
import tempfile

from sdk.git_sync.auth.base import GitAuthProvider


class SSHKeyAuthProvider(GitAuthProvider):
    def __init__(self, private_key_pem: str) -> None:
        self._private_key = private_key_pem
        self.key_path: str | None = None

    def setup(self) -> None:
        fd, path = tempfile.mkstemp(prefix="git_sync_sshkey_", suffix=".pem")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(self._private_key)
        except Exception:
            # Si l'écriture échoue, ne pas laisser le fichier orphelin.
            try:
                os.remove(path)
            finally:
                raise
        # chmod 600 sur Unix ; sur Windows l'appel est un no-op effectif mais
        # ne plante pas — pas de branchement OS spécifique nécessaire.
        os.chmod(path, 0o600)
        self.key_path = path

    def teardown(self) -> None:
        if self.key_path is None:
            return
        try:
            os.remove(self.key_path)
        except FileNotFoundError:
            pass
        finally:
            self.key_path = None

    def get_clone_url(self, repo_url: str) -> str:
        # En SSH, les credentials transitent par la clé, pas par l'URL.
        return repo_url

    def get_env(self) -> dict[str, str]:
        if self.key_path is None:
            raise RuntimeError(
                "SSHKeyAuthProvider.get_env() appelé avant setup() — "
                "appelez setup() avant d'invoquer Git."
            )
        # StrictHostKeyChecking=no : on est sur un repo automatisé sans TTY
        # pour valider l'empreinte. Le risque MITM est mitigé par le fait
        # que repo_url est défini en config (pas par un input utilisateur)
        # et par l'auth applicative sur le serveur Git (PAT, clé, etc.).
        return {
            "GIT_SSH_COMMAND": (
                f"ssh -i {self.key_path} -o StrictHostKeyChecking=no"
            )
        }
