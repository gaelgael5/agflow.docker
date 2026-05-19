"""Wrappers du SDK Git Sync : run_export / run_preview / run_import / test_secret_ref.

Le runner :
  1. lit la config singleton via git_sync_service
  2. résout auth_secret_ref via vault_client (Harpocrate)
  3. construit GitConfig + GitService + Export/ImportService du SDK
  4. délègue l'exécution, capture les exceptions
  5. enregistre le résultat via record_*_run
"""
from __future__ import annotations

from typing import Any

import structlog

from agflow.db.pool import get_pool
from agflow.schemas.git_sync import (
    GitSyncExportResult,
    GitSyncImportPreviewResult,
    GitSyncImportResult,
    GitSyncTablePreview,
    GitSyncTestSecretRefResult,
)
from agflow.services import git_sync_service as svc
from agflow.services import vault_client
from sdk.git_sync import (
    AuthMode,
    ExportService,
    GitConfig,
    GitService,
    ImportService,
    TableRef,
)

_log = structlog.get_logger(__name__)

_MODULE_NAME = "docker"  # spec SDK §2 — un seul module pour agflow.docker


class GitSyncNotConfiguredError(Exception):
    """Aucune config singleton en DB."""


class _ResolvedVaultClient:
    """Wrapper trivial : la valeur est déjà résolue par le runner.

    Le SDK appelle `.resolve(ref)` via _VaultClientProtocol (cf.
    sdk/git_sync/git_service.py:38 et sdk/git_sync/auth/factory.py:21).
    Comme la valeur est déjà résolue, on retourne le secret littéral en
    ignorant le `ref` passé.
    """

    def __init__(self, resolved_value: str) -> None:
        self._value = resolved_value

    async def resolve(self, ref: str) -> str:
        # Valeur déjà résolue par le runner — ref ignoré.
        return self._value

    def get(self, name: str) -> str:
        # Compat défensive — ne devrait jamais être appelé.
        return self._value


async def _build_git_config(config_dto, resolved_auth: str) -> GitConfig:
    return GitConfig(
        repo_url=config_dto.repo_url,
        auth_mode=AuthMode(config_dto.auth_mode),
        auth_secret_ref=resolved_auth,  # littéral — VaultResolver le retourne tel quel
        module_name=_MODULE_NAME,
        commit_author_name=config_dto.commit_author_name,
        commit_author_email=config_dto.commit_author_email,
        branch=config_dto.branch,
        excluded_columns=config_dto.excluded_columns,
    )


def _build_export_service(db_conn: Any, git_service: GitService) -> ExportService:
    return ExportService(db_conn, git_service)


def _build_import_service(db_conn: Any, git_service: GitService) -> ImportService:
    return ImportService(db_conn, git_service)


def _selected_tables_to_refs(selected: list[str]) -> list[TableRef]:
    """`['users', 'public.infra']` → list of TableRef."""
    out: list[TableRef] = []
    for name in selected:
        if "." in name:
            schema, table = name.split(".", 1)
        else:
            schema, table = "public", name
        out.append(TableRef(schema=schema, table=table))
    return out


async def get_config():
    """Indirection pour faciliter le mock dans les tests."""
    return await svc.get_config()


async def run_export() -> GitSyncExportResult:
    """Délègue à ExportService.export(). Met à jour last_export_*."""
    config = await get_config()
    if config is None:
        raise GitSyncNotConfiguredError("git_sync_config is empty — configure first")
    if not config.selected_tables:
        raise ValueError("selected_tables is empty — nothing to export")

    try:
        resolved = await vault_client.resolve_ref(config.auth_secret_ref)
        git_config = await _build_git_config(config, resolved)
        git_service = GitService(git_config, _ResolvedVaultClient(resolved))
        tables = _selected_tables_to_refs(config.selected_tables)
        async with (await get_pool()).acquire() as conn:
            export_svc = _build_export_service(conn, git_service)
            sync_result = await export_svc.export(tables)
    except Exception as exc:
        await svc.record_export_run(
            status="failed", sha=None,
            error=f"{type(exc).__name__}: {exc}",
            tables_count=None,
        )
        raise

    await svc.record_export_run(
        status="ok",
        sha=sync_result.commit_sha,
        error=None,
        tables_count=len(sync_result.tables_exported),
    )
    return GitSyncExportResult(
        sha=sync_result.commit_sha or "",
        tables_count=len(sync_result.tables_exported),
    )


async def run_preview() -> GitSyncImportPreviewResult:
    """Délègue à ImportService.preview(). Pas d'écriture DB persistante."""
    config = await get_config()
    if config is None:
        raise GitSyncNotConfiguredError("git_sync_config is empty — configure first")

    resolved = await vault_client.resolve_ref(config.auth_secret_ref)
    git_config = await _build_git_config(config, resolved)
    git_service = GitService(git_config, _ResolvedVaultClient(resolved))
    tables = _selected_tables_to_refs(config.selected_tables) if config.selected_tables else None
    async with (await get_pool()).acquire() as conn:
        import_svc = _build_import_service(conn, git_service)
        preview = await import_svc.preview(tables)

    return GitSyncImportPreviewResult(
        tables=[
            GitSyncTablePreview(
                table=p.table.full_name,
                to_insert=p.to_insert,
                to_update=p.to_update,
                to_delete=p.to_delete,
            )
            for p in preview.tables
        ]
    )


async def run_import() -> GitSyncImportResult:
    """Délègue à ImportService.import_(). Met à jour last_import_*."""
    config = await get_config()
    if config is None:
        raise GitSyncNotConfiguredError("git_sync_config is empty — configure first")

    try:
        resolved = await vault_client.resolve_ref(config.auth_secret_ref)
        git_config = await _build_git_config(config, resolved)
        git_service = GitService(git_config, _ResolvedVaultClient(resolved))
        tables = _selected_tables_to_refs(config.selected_tables) if config.selected_tables else None
        async with (await get_pool()).acquire() as conn:
            import_svc = _build_import_service(conn, git_service)
            sdk_result = await import_svc.import_(tables)
    except Exception as exc:
        await svc.record_import_run(
            status="failed", error=f"{type(exc).__name__}: {exc}",
            rows_inserted=None, rows_updated=None, rows_deleted=None,
        )
        raise

    total_ins = sum(sdk_result.rows_inserted.values())
    total_upd = sum(sdk_result.rows_updated.values())
    total_del = sum(sdk_result.rows_deleted.values())
    await svc.record_import_run(
        status="ok", error=None,
        rows_inserted=total_ins, rows_updated=total_upd, rows_deleted=total_del,
    )
    return GitSyncImportResult(
        rows_inserted=total_ins,
        rows_updated=total_upd,
        rows_deleted=total_del,
    )


async def test_secret_ref(auth_secret_ref: str) -> GitSyncTestSecretRefResult:
    """Essaie de résoudre la ref Harpocrate, sans rien stocker.

    Retourne ok=True si vault_client.resolve_ref() renvoie une valeur sans
    exception. Le contenu du secret n'est PAS retourné — juste un booléen.
    """
    try:
        await vault_client.resolve_ref(auth_secret_ref)
    except Exception as exc:
        return GitSyncTestSecretRefResult(
            ok=False, error=f"{type(exc).__name__}: {exc}",
        )
    return GitSyncTestSecretRefResult(ok=True)
