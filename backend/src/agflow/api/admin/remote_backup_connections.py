from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

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
from agflow.schemas.remote_backup_files import RemoteBackupFileDTO
from agflow.services import gdrive_oauth_session, users_service, vault_client
from agflow.services import remote_backup_connections_service as rbc_service
from agflow.services.remote_backup_providers import RemoteBackupProviderError
from agflow.services.remote_backup_providers.factory import get_provider

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/backup-remotes",
    tags=["admin", "backup-remotes"],
    dependencies=[Depends(require_admin)],
)

# Public router — pas d'auth JWT requise (Google redirige sans token)
gdrive_public_router = APIRouter(
    prefix="/api/admin/backup-remotes",
    tags=["admin", "backup-remotes"],
)


class GDriveOAuthStartRequest(BaseModel):
    name: str = Field(min_length=1)
    folder_name: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)


class GDriveOAuthStartResponse(BaseModel):
    state: str
    authorize_url: str


class GDriveOAuthSessionResponse(BaseModel):
    status: str
    connection_id: str | None
    user_email: str | None
    folder_id: str | None


# ---------------------------------------------------------------------------
# Collection endpoints (no path param — must come before /{connection_id})
# ---------------------------------------------------------------------------


@router.get("", response_model=list[RemoteBackupConnectionSummary])
async def list_connections() -> list[RemoteBackupConnectionSummary]:
    async with (await get_pool()).acquire() as conn:
        return await rbc_service.list_connections(conn)


@router.post("", response_model=RemoteBackupConnectionSummary, status_code=201)
async def create_connection(
    body: RemoteBackupConnectionCreate,
    admin_email: str = Depends(require_admin),
) -> RemoteBackupConnectionSummary:
    if body.kind == "gdrive":
        raise HTTPException(
            status_code=400,
            detail="kind='gdrive' must be created via /api/admin/backup-remotes/oauth/gdrive/start",
        )
    admin_user = await users_service.get_by_email(admin_email)
    user_uuid = admin_user.id if admin_user else None
    try:
        async with (await get_pool()).acquire() as conn:
            connection_id = await rbc_service.create_connection(
                conn,
                name=body.name,
                kind=body.kind,
                config=body.config,
                credentials=body.credentials,
                created_by_user_id=user_uuid,
            )
            dto = await rbc_service.get_connection(conn, connection_id)
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=409, detail="A connection with this name already exists"
        ) from exc
    except vault_client.VaultNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return dto  # type: ignore[return-value]


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


# ---------------------------------------------------------------------------
# OAuth Google Drive endpoints (static paths — must come before /{connection_id})
# ---------------------------------------------------------------------------


@router.get("/oauth/gdrive/redirect-uri")
async def gdrive_redirect_uri(request: Request) -> dict:
    """Retourne l'URI de callback à coller dans Google Cloud Console."""
    base = str(request.base_url).rstrip("/")
    return {"redirect_uri": f"{base}/api/admin/backup-remotes/oauth/gdrive/callback"}


@router.post("/oauth/gdrive/start", response_model=GDriveOAuthStartResponse)
async def gdrive_oauth_start(
    payload: GDriveOAuthStartRequest,
    request: Request,
    admin_email: str = Depends(require_admin),
) -> GDriveOAuthStartResponse:
    admin_user = await users_service.get_by_email(admin_email)
    if admin_user is None:
        raise HTTPException(status_code=403, detail="Admin user not found")
    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/admin/backup-remotes/oauth/gdrive/callback"
    state, url = await gdrive_oauth_session.start_session(
        actor_user_id=admin_user.id,
        name=payload.name,
        folder_name=payload.folder_name,
        client_id=payload.client_id,
        client_secret=payload.client_secret,
        redirect_uri=redirect_uri,
    )
    return GDriveOAuthStartResponse(state=state, authorize_url=url)


@gdrive_public_router.get(
    "/oauth/gdrive/callback",
    response_class=HTMLResponse,
)
async def gdrive_oauth_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    """Public endpoint — Google nous appelle sans cookie de session.

    Validation par le state token uniquement. Retourne du HTML qui ferme
    le popup et notifie l'opener.
    """
    if error or not code:
        html = (
            f"<!DOCTYPE html><html><body><script>"
            f"window.opener && window.opener.postMessage({{type: 'gdrive-oauth-failed', error: {error!r}}}, '*');"
            f"window.close();"
            f"</script>Failed: {error or 'no code'}</body></html>"
        )
        return HTMLResponse(html, status_code=200)
    try:
        await gdrive_oauth_session.consume_session(state=state, code=code)
    except gdrive_oauth_session.PendingSessionError as exc:
        html = (
            f"<!DOCTYPE html><html><body><script>"
            f"window.opener && window.opener.postMessage({{type: 'gdrive-oauth-failed', error: {str(exc)!r}}}, '*');"
            f"window.close();"
            f"</script>{exc}</body></html>"
        )
        return HTMLResponse(html, status_code=200)
    html = (
        "<!DOCTYPE html><html><body><script>"
        "window.opener && window.opener.postMessage({type: 'gdrive-oauth-completed'}, '*');"
        "window.close();"
        "</script>OAuth completed. You can close this window.</body></html>"
    )
    return HTMLResponse(html, status_code=200)


@router.get("/oauth/gdrive/session/{state}", response_model=GDriveOAuthSessionResponse)
async def gdrive_oauth_session_status(
    state: str,
    admin_email: str = Depends(require_admin),
) -> GDriveOAuthSessionResponse:
    info = await gdrive_oauth_session.get_session(state)
    if info is None:
        raise HTTPException(status_code=404, detail="OAuth state not found")
    return GDriveOAuthSessionResponse(
        status=info["status"],
        connection_id=str(info["connection_id"]) if info.get("connection_id") else None,
        user_email=info.get("user_email"),
        folder_id=info.get("folder_id"),
    )


# ---------------------------------------------------------------------------
# Item endpoints (path param /{connection_id} — after static paths)
# ---------------------------------------------------------------------------


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
) -> RemoteBackupConnectionSummary:
    try:
        async with (await get_pool()).acquire() as conn:
            await rbc_service.update_connection(
                conn,
                connection_id,
                name=body.name,
                config=body.config,
                credentials=body.credentials,
            )
            dto = await rbc_service.get_connection(conn, connection_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except vault_client.VaultNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if dto is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return dto


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(connection_id: UUID) -> None:
    async with (await get_pool()).acquire() as conn:
        await rbc_service.delete_connection(conn, connection_id)


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
    except Exception as exc:
        _log.warning("rbc.test_connection_saved.unexpected", error=str(exc))
        return TestConnectionResult(ok=False, error="unexpected", message=str(exc))


@router.get("/{connection_id}/files", response_model=list[RemoteBackupFileDTO])
async def list_remote_files(connection_id: UUID) -> list[RemoteBackupFileDTO]:
    """Liste les fichiers présents sur la cible distante (usage='full')."""
    async with (await get_pool()).acquire() as conn:
        dto = await rbc_service.get_connection(conn, connection_id)
        if dto is None:
            raise HTTPException(status_code=404, detail="Connection not found")
        credentials = await rbc_service.fetch_credentials(dto)

    if credentials is None:
        raise HTTPException(status_code=422, detail="No credentials configured")

    remote_path = rbc_service.resolve_remote_path(dto.config, dto.kind, "full")
    if remote_path is None:
        raise HTTPException(
            status_code=422, detail="No full backup path configured"
        )

    try:
        provider = get_provider(dto.kind, dto.config, credentials)
        files = await provider.list_remote(remote_path)
    except RemoteBackupProviderError as exc:
        _log.warning("list_remote_files.provider_error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return [
        RemoteBackupFileDTO(
            filename=f.filename,
            size_bytes=f.size_bytes,
            last_modified=f.last_modified,
        )
        for f in files
    ]


@router.post("/{connection_id}/reauthorize", response_model=GDriveOAuthStartResponse)
async def gdrive_reauthorize(
    connection_id: UUID,
    admin_email: str = Depends(require_admin),
) -> GDriveOAuthStartResponse:
    admin_user = await users_service.get_by_email(admin_email)
    if admin_user is None:
        raise HTTPException(status_code=403, detail="Admin user not found")
    try:
        state, url = await gdrive_oauth_session.reauthorize(
            connection_id=connection_id,
            actor_user_id=admin_user.id,
        )
    except gdrive_oauth_session.PendingSessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GDriveOAuthStartResponse(state=state, authorize_url=url)
