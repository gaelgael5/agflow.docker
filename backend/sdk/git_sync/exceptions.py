"""Hiérarchie d'exceptions du SDK Git Sync.

Toutes les erreurs spécifiques héritent de `GitSyncError`, ce qui permet
au code consommateur de catcher l'ensemble des erreurs SDK avec un seul
except sans dépendre des classes filles.
"""
from __future__ import annotations


class GitSyncError(Exception):
    """Base de toutes les exceptions du SDK."""


class GitAuthError(GitSyncError):
    """Clé invalide, token expiré, accès refusé."""


class GitCloneError(GitSyncError):
    """Échec du clone (réseau, URL incorrecte)."""


class GitPushError(GitSyncError):
    """Échec du push."""


class GitConflictError(GitSyncError):
    """`--ff-only` échoue — conflit détecté."""


class GitDirtyRepoError(GitSyncError):
    """Répertoire temporaire dans un état inattendu."""


class DependencyResolveError(GitSyncError):
    """Cycle détecté dans le graphe FK ou structure de graphe invalide."""


class ImportConflictError(GitSyncError):
    """Erreur lors du MERGE PostgreSQL."""


class TableNotFoundError(GitSyncError):
    """Table référencée dans CSV introuvable en base."""


class VaultResolutionError(GitSyncError):
    """Échec de résolution du secret Harpocrate."""
