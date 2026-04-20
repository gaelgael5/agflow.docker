from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.catalogs import (
    MCPInstallPayload,
    MCPParametersUpdate,
    MCPServerSummary,
)
from agflow.services import mcp_catalog_service

router = APIRouter(
    prefix="/api/admin/mcp-catalog",
    tags=["admin-mcp-catalog"],
    dependencies=[Depends(require_admin)],
)


@router.get(
    "",
    response_model=list[MCPServerSummary],
    summary="List installed MCP servers",
    description="Returns all MCP servers installed in the local catalog with their metadata, transport type, and recipes.",
)
async def list_mcps() -> list[MCPServerSummary]:
    return await mcp_catalog_service.list_all()


@router.post(
    "",
    response_model=MCPServerSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Install an MCP server into the catalog",
    description="Installs an MCP server from a discovery service into the local catalog using the provided package ID, recipes, parameters, and category. Returns 409 if the server is already installed.",
)
async def install_mcp(payload: MCPInstallPayload) -> MCPServerSummary:
    try:
        return await mcp_catalog_service.install(
            discovery_service_id=payload.discovery_service_id,
            package_id=str(payload.package_id),
            recipes=payload.recipes,
            parameters=payload.parameters,
            category=payload.category,
        )
    except mcp_catalog_service.DuplicateMCPServerError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.put(
    "/{mcp_id}",
    response_model=MCPServerSummary,
    summary="Update MCP server parameters",
    description="Updates the runtime parameters of an installed MCP server by its UUID. Returns 404 if the server is not found.",
)
async def update_mcp_parameters(
    mcp_id: UUID, payload: MCPParametersUpdate
) -> MCPServerSummary:
    try:
        return await mcp_catalog_service.update_parameters(
            mcp_id, payload.parameters
        )
    except mcp_catalog_service.MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete(
    "/{mcp_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Uninstall an MCP server from the catalog",
    description="Removes an MCP server from the local catalog by its UUID. Returns 404 if the server is not found.",
)
async def delete_mcp(mcp_id: UUID) -> None:
    try:
        await mcp_catalog_service.delete(mcp_id)
    except mcp_catalog_service.MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
