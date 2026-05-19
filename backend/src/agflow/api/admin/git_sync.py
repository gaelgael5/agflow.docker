"""Endpoints REST /api/admin/git-sync (9 endpoints, require_admin global)."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from agflow.auth.dependencies import require_admin
from agflow.schemas.git_sync import (
    GitSyncCommitDTO,
    GitSyncConfigDTO,
    GitSyncConfigUpsert,
    GitSyncExportResult,
    GitSyncImportPreviewResult,
    GitSyncImportResult,
    GitSyncTestSecretRefRequest,
    GitSyncTestSecretRefResult,
)
from agflow.services import git_sync_github_client as gh
from agflow.services import git_sync_runner, git_sync_scheduler, vault_client
from agflow.services import git_sync_service as svc

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/git-sync",
    tags=["admin", "git-sync"],
    dependencies=[Depends(require_admin)],
)


@router.get("/config", response_model=GitSyncConfigDTO)
async def get_config() -> GitSyncConfigDTO:
    config = await svc.get_config()
    if config is None:
        raise HTTPException(status_code=404, detail="Git sync not configured")
    return config


@router.put("/config", response_model=GitSyncConfigDTO)
async def put_config(body: GitSyncConfigUpsert) -> GitSyncConfigDTO:
    config = await svc.upsert_config(
        repo_url=body.repo_url,
        auth_mode=body.auth_mode,
        auth_secret_ref=body.auth_secret_ref,
        branch=body.branch,
        commit_author_name=body.commit_author_name,
        commit_author_email=body.commit_author_email,
        excluded_columns=body.excluded_columns,
        selected_tables=body.selected_tables,
        cron_expr=body.cron_expr,
        cron_enabled=body.cron_enabled,
    )
    await git_sync_scheduler.reload_schedule()
    return config


@router.delete("/config", status_code=204)
async def delete_config() -> None:
    await svc.delete_config()
    await git_sync_scheduler.reload_schedule()


@router.get("/available-tables", response_model=list[str])
async def get_available_tables() -> list[str]:
    return await svc.list_available_tables()


@router.post("/test-secret-ref", response_model=GitSyncTestSecretRefResult)
async def post_test_secret_ref(
    body: GitSyncTestSecretRefRequest,
) -> GitSyncTestSecretRefResult:
    return await git_sync_runner.test_secret_ref(body.auth_secret_ref)


@router.post("/export", response_model=GitSyncExportResult)
async def post_export() -> GitSyncExportResult:
    try:
        return await git_sync_runner.run_export()
    except git_sync_runner.GitSyncNotConfiguredError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _log.warning("git_sync.api.export_failed", error=str(exc))
        raise HTTPException(
            status_code=502, detail=f"{type(exc).__name__}: {exc}"
        ) from exc


@router.post("/preview-import", response_model=GitSyncImportPreviewResult)
async def post_preview_import() -> GitSyncImportPreviewResult:
    try:
        return await git_sync_runner.run_preview()
    except git_sync_runner.GitSyncNotConfiguredError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _log.warning("git_sync.api.preview_failed", error=str(exc))
        raise HTTPException(
            status_code=502, detail=f"{type(exc).__name__}: {exc}"
        ) from exc


@router.post("/import", response_model=GitSyncImportResult)
async def post_import() -> GitSyncImportResult:
    try:
        return await git_sync_runner.run_import()
    except git_sync_runner.GitSyncNotConfiguredError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _log.warning("git_sync.api.import_failed", error=str(exc))
        raise HTTPException(
            status_code=502, detail=f"{type(exc).__name__}: {exc}"
        ) from exc


@router.get("/commits", response_model=list[GitSyncCommitDTO])
async def get_commits(
    limit: int = Query(default=30, ge=1, le=100),
) -> list[GitSyncCommitDTO]:
    config = await svc.get_config()
    if config is None:
        raise HTTPException(status_code=404, detail="Git sync not configured")

    # Résout le PAT (auth_secret_ref) pour appeler l'API GitHub en mode
    # authentifié. Sans ça, un repo privé renvoie 404 (sécurité par obscurité).
    # En mode SSH_KEY le secret est une clé SSH, pas un PAT — on saute l'auth.
    auth_token: str | None = None
    if config.auth_mode != "ssh_key":
        try:
            auth_token = await vault_client.resolve_ref(config.auth_secret_ref)
        except Exception as exc:
            _log.warning("git_sync.api.commits_secret_resolve_failed", error=str(exc))

    try:
        commits = await gh.list_commits(
            repo_url=config.repo_url,
            branch=config.branch,
            limit=limit,
            auth_token=auth_token,
        )
    except gh.UnsupportedHostError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _log.warning("git_sync.api.commits_failed", error=str(exc))
        raise HTTPException(
            status_code=502, detail=f"{type(exc).__name__}: {exc}"
        ) from exc

    return [
        GitSyncCommitDTO(
            sha=c.sha,
            short_sha=c.short_sha,
            message=c.message,
            author_name=c.author_name,
            author_email=c.author_email,
            authored_at=c.authored_at,
            html_url=c.html_url,
        )
        for c in commits
    ]
