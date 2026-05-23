from __future__ import annotations

import structlog
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from agflow.auth.dependencies import require_admin
from agflow.schemas.restore_wizard import (
    RemoteBrowseRequest,
    RemoteEntry,
    RestoreExecuteRequest,
    RestoreJobStarted,
    RestoreJobStatus,
    VaultRef,
    VaultSecretsRequest,
    VaultSecretItem,
)
from agflow.services.restore_wizard_browse_service import browse_remote
from agflow.services.restore_wizard_job_service import (
    create_job,
    get_job,
    run_job,
)
from agflow.services.restore_wizard_vault_service import (
    InvalidVaultCredentialsError,
    get_vault_secret_value,
    list_vault_secrets_by_prefix,
    test_vault_connection,
)

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/restore",
    tags=["admin", "restore"],
    dependencies=[Depends(require_admin)],
)


@router.post("/vault/test", status_code=200)
async def vault_test(body: VaultRef) -> dict:
    try:
        await test_vault_connection(body.url, body.api_key)
    except InvalidVaultCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {}


@router.post("/vault/secrets", response_model=list[VaultSecretItem])
async def vault_secrets(body: VaultSecretsRequest) -> list[VaultSecretItem]:
    try:
        return await list_vault_secrets_by_prefix(body.url, body.api_key, body.path)
    except InvalidVaultCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/remote/browse", response_model=list[RemoteEntry])
async def remote_browse(body: RemoteBrowseRequest) -> list[RemoteEntry]:
    credentials: dict[str, str | None] = {}
    for field, secret_name in body.vault_mappings.items():
        if secret_name:
            credentials[field] = await get_vault_secret_value(
                body.vault.url, body.vault.api_key, secret_name
            )

    try:
        return await browse_remote(
            connection_type=body.connection_type,
            manual_fields={**body.manual_fields, "path": body.path},
            credentials=credentials,
        )
    except InvalidVaultCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        _log.error("restore.browse_failed", error=str(exc))
        raise HTTPException(status_code=502, detail="Connexion distante échouée") from exc


@router.post("/execute", status_code=202, response_model=RestoreJobStarted)
async def execute_restore(
    body: RestoreExecuteRequest,
    background_tasks: BackgroundTasks,
) -> RestoreJobStarted:
    job_id = await create_job()
    background_tasks.add_task(run_job, job_id, body)
    return RestoreJobStarted(job_id=job_id)


@router.get("/execute/{job_id}", response_model=RestoreJobStatus)
async def get_restore_job(job_id: UUID) -> RestoreJobStatus:
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return job
