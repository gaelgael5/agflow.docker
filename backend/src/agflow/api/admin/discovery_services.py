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
    discovery_services_service as svc,
)

router = APIRouter(
    prefix="/api/admin/discovery-services",
    tags=["admin-discovery"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[DiscoveryServiceSummary])
async def list_services() -> list[DiscoveryServiceSummary]:
    return await svc.list_all()


@router.post(
    "", response_model=DiscoveryServiceSummary, status_code=status.HTTP_201_CREATED
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


@router.put("/{service_id}", response_model=DiscoveryServiceSummary)
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


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(service_id: str) -> None:
    try:
        await svc.delete(service_id)
    except svc.DiscoveryServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/{service_id}/test", response_model=ProbeResult)
async def test_service(service_id: str) -> ProbeResult:
    try:
        return await svc.test_connectivity(service_id)
    except svc.DiscoveryServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get("/{service_id}/search/mcp", response_model=list[MCPSearchItem])
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


@router.get("/{service_id}/summary/{package_id}")
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


@router.get("/{service_id}/search/skills", response_model=list[SkillSearchItem])
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
