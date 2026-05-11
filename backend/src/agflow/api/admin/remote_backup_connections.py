from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException

from agflow.auth.dependencies import require_admin
from agflow.db.pool import get_pool
from agflow.schemas.remote_backup_connections import (
    RemoteBackupConnectionCreate,
    RemoteBackupConnectionSummary,
    RemoteBackupConnectionUpdate,
    TestConnectionRequest,
    TestConnectionResult,
    TestConnectionWithIdRequest,
)
from agflow.services import remote_backup_connections_service as rbc_service
from agflow.services.remote_backup_providers import RemoteBackupProviderError
from agflow.services.remote_backup_providers.factory import get_provider

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/backup-remotes",
    tags=["admin", "backup-remotes"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[RemoteBackupConnectionSummary])
async def list_connections() -> list[RemoteBackupConnectionSummary]:
    async with (await get_pool()).acquire() as conn:
        return await rbc_service.list_connections(conn)


@router.post("", response_model=RemoteBackupConnectionSummary, status_code=201)
async def create_connection(
    body: RemoteBackupConnectionCreate,
    _user_id: str = Depends(require_admin),
) -> RemoteBackupConnectionSummary:
    try:
        async with (await get_pool()).acquire() as conn:
            connection_id = await rbc_service.create_connection(
                conn,
                name=body.name,
                kind=body.kind,
                config=body.config,
                credentials=body.credentials,
                created_by_user_id=None,
            )
            dto = await rbc_service.get_connection(conn, connection_id)
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=409, detail="A connection with this name already exists"
        ) from exc
    return dto  # type: ignore[return-value]


@router.get("/{connection_id}", response_model=RemoteBackupConnectionSummary)
async def get_connection(connection_id: UUID) -> RemoteBackupConnectionSummary:
    async with (await get_pool()).acquire() as conn:
        dto = await rbc_service.get_connection(conn, connection_id)
    if dto is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return dto


@router.patch("/{connection_id}", response_model=RemoteBackupConnectionSummary)
async def update_connection(
    connection_id: UUID, body: RemoteBackupConnectionUpdate
) -> RemoteBackupConnectionSummary | None:
    async with (await get_pool()).acquire() as conn:
        await rbc_service.update_connection(
            conn,
            connection_id,
            name=body.name,
            config=body.config,
            credentials=body.credentials,
        )
        return await rbc_service.get_connection(conn, connection_id)


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(connection_id: UUID) -> None:
    async with (await get_pool()).acquire() as conn:
        await rbc_service.delete_connection(conn, connection_id)


@router.post("/test", response_model=TestConnectionResult)
async def test_connection_unsaved(body: TestConnectionRequest) -> TestConnectionResult:
    """Test avec creds fournis dans le body (création / édition avec resaisie)."""
    try:
        provider = get_provider(body.kind, body.config, body.credentials)
        await provider.test_connection(body.path)
        return TestConnectionResult(ok=True)
    except RemoteBackupProviderError as exc:
        return TestConnectionResult(ok=False, error="provider_error", message=str(exc))
    except Exception as exc:
        _log.warning("rbc.test_connection.unexpected", error=str(exc))
        return TestConnectionResult(ok=False, error="unexpected", message=str(exc))


@router.post("/{connection_id}/test", response_model=TestConnectionResult)
async def test_connection_saved(
    connection_id: UUID, body: TestConnectionWithIdRequest
) -> TestConnectionResult:
    """Test avec creds stockés en vault (édition sans resaisie)."""
    async with (await get_pool()).acquire() as conn:
        dto = await rbc_service.get_connection(conn, connection_id)
        if dto is None:
            raise HTTPException(status_code=404, detail="Connection not found")
        config = {**dto.config, **(body.config or {})}
        credentials = await rbc_service.fetch_credentials(dto)
    if credentials is None:
        return TestConnectionResult(
            ok=False,
            error="no_credentials",
            message="No credentials stored for this connection",
        )
    try:
        provider = get_provider(dto.kind, config, credentials)
        await provider.test_connection(body.path)
        return TestConnectionResult(ok=True)
    except RemoteBackupProviderError as exc:
        return TestConnectionResult(ok=False, error="provider_error", message=str(exc))
