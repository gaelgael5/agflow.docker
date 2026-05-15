"""Interface commune aux providers Git auth (ABC)."""
from __future__ import annotations

from abc import ABC, abstractmethod


class GitAuthProvider(ABC):
    """Cycle de vie : setup() → get_clone_url() + get_env() → teardown().

    Le `teardown()` DOIT être appelé dans un `finally` pour garantir le
    nettoyage des ressources (typiquement le fichier de clé SSH temporaire).
    """

    @abstractmethod
    def setup(self) -> None:
        """Préparation avant usage. SSH : écrit la clé en tmp. HTTPS : no-op."""

    @abstractmethod
    def teardown(self) -> None:
        """Nettoyage. SSH : supprime le fichier tmp. HTTPS : no-op.

        Doit être idempotent : appeler teardown() plusieurs fois (ou sans
        setup préalable) ne doit lever aucune exception.
        """

    @abstractmethod
    def get_clone_url(self, repo_url: str) -> str:
        """SSH : URL inchangée. HTTPS : injecte les credentials dans l'URL."""

    @abstractmethod
    def get_env(self) -> dict[str, str]:
        """SSH : {GIT_SSH_COMMAND: ...}. HTTPS : {}."""
