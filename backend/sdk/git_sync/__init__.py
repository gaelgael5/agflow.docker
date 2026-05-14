"""SDK Git Sync — export/import de snapshots de configuration via Git.

Spec : specs/sdk_git_sync_specs.md (v1.0).
"""
from __future__ import annotations

from sdk.git_sync.exceptions import (
    DependencyResolveError,
    GitAuthError,
    GitCloneError,
    GitConflictError,
    GitDirtyRepoError,
    GitPushError,
    GitSyncError,
    ImportConflictError,
    TableNotFoundError,
    VaultResolutionError,
)
from sdk.git_sync.git_service import GitService
from sdk.git_sync.models import (
    AuthMode,
    DependencyGraph,
    GitConfig,
    ImportPreview,
    ImportResult,
    SyncResult,
    TablePreview,
    TableRef,
)
from sdk.git_sync.vault_resolver import VaultResolver, is_vault_ref

__all__ = [
    "AuthMode",
    "DependencyGraph",
    "DependencyResolveError",
    "GitAuthError",
    "GitCloneError",
    "GitConfig",
    "GitConflictError",
    "GitDirtyRepoError",
    "GitPushError",
    "GitService",
    "GitSyncError",
    "ImportConflictError",
    "ImportPreview",
    "ImportResult",
    "SyncResult",
    "TableNotFoundError",
    "TablePreview",
    "TableRef",
    "VaultResolutionError",
    "VaultResolver",
    "is_vault_ref",
]
