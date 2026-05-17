"""CRUD config singleton git_sync_config + utilitaires DB."""
from __future__ import annotations

import json
from typing import Any

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.git_sync import GitSyncConfigDTO

_log = structlog.get_logger(__name__)


def _row_to_dto(row: dict[str, Any]) -> GitSyncConfigDTO:
    """Convertit une row asyncpg en GitSyncConfigDTO (parse JSONB → dict/list)."""
    excluded = row["excluded_columns"]
    if isinstance(excluded, str):
        excluded = json.loads(excluded)
    selected = row["selected_tables"]
    if isinstance(selected, str):
        selected = json.loads(selected)
    return GitSyncConfigDTO(
        repo_url=row["repo_url"],
        auth_mode=row["auth_mode"],
        auth_secret_ref=row["auth_secret_ref"],
        branch=row["branch"],
        commit_author_name=row["commit_author_name"],
        commit_author_email=row["commit_author_email"],
        excluded_columns=excluded,
        selected_tables=selected,
        cron_expr=row["cron_expr"],
        cron_enabled=row["cron_enabled"],
        last_export_at=row["last_export_at"],
        last_export_status=row["last_export_status"],
        last_export_sha=row["last_export_sha"],
        last_export_error=row["last_export_error"],
        last_export_tables_count=row["last_export_tables_count"],
        last_import_at=row["last_import_at"],
        last_import_status=row["last_import_status"],
        last_import_error=row["last_import_error"],
        last_import_rows_inserted=row["last_import_rows_inserted"],
        last_import_rows_updated=row["last_import_rows_updated"],
        last_import_rows_deleted=row["last_import_rows_deleted"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def get_config() -> GitSyncConfigDTO | None:
    """Lit la config singleton. None si la table est vide."""
    row = await fetch_one("SELECT * FROM git_sync_config WHERE id = 1")
    return _row_to_dto(row) if row else None


async def upsert_config(
    *,
    repo_url: str,
    auth_mode: str,
    auth_secret_ref: str,
    branch: str,
    commit_author_name: str,
    commit_author_email: str,
    excluded_columns: dict[str, list[str]],
    selected_tables: list[str],
    cron_expr: str | None,
    cron_enabled: bool,
) -> GitSyncConfigDTO:
    """INSERT (1) ON CONFLICT (id) DO UPDATE — préserve les last_* existants."""
    await execute(
        """
        INSERT INTO git_sync_config (
            id, repo_url, auth_mode, auth_secret_ref,
            branch, commit_author_name, commit_author_email,
            excluded_columns, selected_tables,
            cron_expr, cron_enabled
        )
        VALUES (1, $1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10)
        ON CONFLICT (id) DO UPDATE SET
            repo_url             = EXCLUDED.repo_url,
            auth_mode            = EXCLUDED.auth_mode,
            auth_secret_ref      = EXCLUDED.auth_secret_ref,
            branch               = EXCLUDED.branch,
            commit_author_name   = EXCLUDED.commit_author_name,
            commit_author_email  = EXCLUDED.commit_author_email,
            excluded_columns     = EXCLUDED.excluded_columns,
            selected_tables      = EXCLUDED.selected_tables,
            cron_expr            = EXCLUDED.cron_expr,
            cron_enabled         = EXCLUDED.cron_enabled
        """,
        repo_url, auth_mode, auth_secret_ref,
        branch, commit_author_name, commit_author_email,
        json.dumps(excluded_columns), json.dumps(selected_tables),
        cron_expr, cron_enabled,
    )
    _log.info("git_sync.config.upserted", repo_url=repo_url, branch=branch)
    config = await get_config()
    assert config is not None
    return config


async def delete_config() -> None:
    """Supprime la ligne singleton (réinit complète)."""
    await execute("DELETE FROM git_sync_config WHERE id = 1")
    _log.info("git_sync.config.deleted")


async def list_available_tables() -> list[str]:
    """Liste les tables du schéma public, triées alphabétiquement."""
    rows = await fetch_all(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    )
    return [r["table_name"] for r in rows]


async def record_export_run(
    *,
    status: str,
    sha: str | None,
    error: str | None,
    tables_count: int | None,
) -> None:
    """Met à jour les colonnes last_export_*."""
    await execute(
        """
        UPDATE git_sync_config
        SET last_export_at = now(),
            last_export_status = $1,
            last_export_sha = $2,
            last_export_error = $3,
            last_export_tables_count = $4
        WHERE id = 1
        """,
        status, sha, error, tables_count,
    )


async def record_import_run(
    *,
    status: str,
    error: str | None,
    rows_inserted: int | None,
    rows_updated: int | None,
    rows_deleted: int | None,
) -> None:
    """Met à jour les colonnes last_import_*."""
    await execute(
        """
        UPDATE git_sync_config
        SET last_import_at = now(),
            last_import_status = $1,
            last_import_error = $2,
            last_import_rows_inserted = $3,
            last_import_rows_updated = $4,
            last_import_rows_deleted = $5
        WHERE id = 1
        """,
        status, error, rows_inserted, rows_updated, rows_deleted,
    )
