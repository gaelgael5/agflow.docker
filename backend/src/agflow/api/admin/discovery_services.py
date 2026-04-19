from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.catalogs import (
    DiscoveryServiceCreate,
    DiscoveryServiceSummary,
    DiscoveryServiceUpdate,
    MCPSearchItem,
    ProbeResult,
    SkillSearchItem,
)
from agflow.services import (
    discovery_client,
)
from agflow.services import (
    discovery_services_service as svc,
)

router = APIRouter(
    prefix="/api/admin/discovery-services",
    tags=["admin-discovery"],
    dependencies=[Depends(require_admin)],
)


@router.get(
    "",
    response_model=list[DiscoveryServiceSummary],
    summary="List discovery services",
    description="Returns all configured discovery services (MCP registries) with their connection settings and enabled status.",
)
async def list_services() -> list[DiscoveryServiceSummary]:
    return await svc.list_all()


@router.post(
    "",
    response_model=DiscoveryServiceSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new discovery service",
    description="Creates a new discovery service (MCP registry) with the provided base URL, API key reference, and metadata. Returns 409 if a service with the same ID already exists.",
)
async def create_service(
    payload: DiscoveryServiceCreate,
) -> DiscoveryServiceSummary:
    try:
        return await svc.create(
            service_id=payload.id,
            name=payload.name,
            base_url=payload.base_url,
            api_key_var=payload.api_key_var,
            description=payload.description,
            enabled=payload.enabled,
        )
    except svc.DuplicateDiscoveryServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.put(
    "/{service_id}",
    response_model=DiscoveryServiceSummary,
    summary="Update a discovery service",
    description="Partially updates a discovery service's properties (name, base URL, API key variable, enabled state). Returns 404 if the service is not found.",
)
async def update_service(
    service_id: str, payload: DiscoveryServiceUpdate
) -> DiscoveryServiceSummary:
    try:
        return await svc.update(
            service_id, **payload.model_dump(exclude_unset=True)
        )
    except svc.DiscoveryServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete(
    "/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a discovery service",
    description="Permanently removes a discovery service from the database. Returns 404 if the service is not found.",
)
async def delete_service(service_id: str) -> None:
    try:
        await svc.delete(service_id)
    except svc.DiscoveryServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/{service_id}/test",
    response_model=ProbeResult,
    summary="Test connectivity to a discovery service",
    description="Probes the specified discovery service by performing an HTTP health check against its base URL and returns the latency and status. Returns 404 if the service is not found.",
)
async def test_service(service_id: str) -> ProbeResult:
    try:
        return await svc.test_connectivity(service_id)
    except svc.DiscoveryServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get(
    "/{service_id}/search/mcp",
    response_model=list[MCPSearchItem],
    summary="Search MCP packages in a discovery service",
    description="Searches MCP packages available in the specified discovery service registry, with optional keyword or semantic search. Returns 404 if the service is not found.",
)
async def search_mcp(
    service_id: str,
    q: str = Query(""),
    semantic: bool = Query(False),
) -> list[MCPSearchItem]:
    try:
        service = await svc.get_by_id(service_id)
    except svc.DiscoveryServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    api_key = await svc._resolve_api_key(service.api_key_var)
    items = await discovery_client.search_mcp(
        service.base_url, api_key, q, semantic=semantic
    )
    return [MCPSearchItem(**item) for item in items]


@router.get(
    "/{service_id}/summary/{package_id}",
    summary="Get localized summary for an MCP package",
    description="Fetches the human-readable summary for a specific MCP package from a discovery service in the requested culture/language. Returns 404 if no summary is available.",
)
async def get_summary(
    service_id: str,
    package_id: str,
    culture: str = Query("fr"),
) -> dict:
    """Fetch the summary (in the given culture/language) for a specific MCP service."""
    try:
        service = await svc.get_by_id(service_id)
    except svc.DiscoveryServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    api_key = await svc._resolve_api_key(service.api_key_var)
    text = await discovery_client.get_service_summary(
        service.base_url, api_key, package_id, culture=culture
    )
    if text is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No summary found for service {package_id} in {culture}",
        )
    return {"summary": text, "culture": culture, "package_id": package_id}


@router.get(
    "/{service_id}/search/skills",
    response_model=list[SkillSearchItem],
    summary="Search skills in a discovery service",
    description="Searches skills available in the specified discovery service registry with optional keyword filtering. Returns 404 if the service is not found.",
)
async def search_skills(
    service_id: str,
    q: str = Query(""),
) -> list[SkillSearchItem]:
    try:
        service = await svc.get_by_id(service_id)
    except svc.DiscoveryServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    api_key = await svc._resolve_api_key(service.api_key_var)
    items = await discovery_client.search_skills(
        service.base_url, api_key, q
    )
    return [SkillSearchItem(**item) for item in items]


@router.get(
    "/{service_id}/targets",
    summary="List targets from a discovery service",
    description="Proxies a GET /targets request to the remote discovery service registry and returns the list of available deployment targets. Returns 404 if the service is not found.",
)
async def list_targets(service_id: str) -> list[dict]:
    """Proxy to registry GET /targets."""
    try:
        service = await svc.get_by_id(service_id)
    except svc.DiscoveryServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    api_key = await svc._resolve_api_key(service.api_key_var)
    return await discovery_client.fetch_targets(service.base_url, api_key)
