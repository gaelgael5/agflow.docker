from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from agflow.auth.dependencies import require_admin
from agflow.schemas.contracts import (
    ContractCreate,
    ContractDetail,
    ContractSummary,
    ContractUpdate,
)
from agflow.services import api_contracts_service

router = APIRouter(
    prefix="/api/admin/agents/{agent_id}/contracts",
    tags=["admin-contracts"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[ContractSummary])
async def list_contracts(agent_id: str):
    return await api_contracts_service.list_for_agent(agent_id)


@router.post("", response_model=ContractSummary, status_code=status.HTTP_201_CREATED)
async def create_contract(agent_id: str, payload: ContractCreate):
    try:
        return await api_contracts_service.create(
            agent_id=agent_id,
            slug=payload.slug,
            display_name=payload.display_name,
            description=payload.description,
            source_type=payload.source_type,
            source_url=payload.source_url,
            spec_content=payload.spec_content,
            base_url=payload.base_url,
            auth_header=payload.auth_header,
            auth_prefix=payload.auth_prefix,
            auth_secret_ref=payload.auth_secret_ref,
        )
    except api_contracts_service.DuplicateContractError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{contract_id}", response_model=ContractDetail)
async def get_contract(contract_id: UUID):
    try:
        return await api_contracts_service.get_by_id(contract_id)
    except api_contracts_service.ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{contract_id}", response_model=ContractSummary)
async def update_contract(contract_id: UUID, payload: ContractUpdate):
    try:
        return await api_contracts_service.update(
            contract_id, **payload.model_dump(exclude_unset=True)
        )
    except api_contracts_service.ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(contract_id: UUID):
    try:
        await api_contracts_service.delete(contract_id)
    except api_contracts_service.ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


class FetchSpecRequest(BaseModel):
    url: str


@router.post("/fetch-spec")
async def fetch_spec(agent_id: str, payload: FetchSpecRequest):
    """Utilitaire : fetch une URL OpenAPI et retourne le contenu pour preview."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=True
        ) as client:
            response = await client.get(payload.url)
            response.raise_for_status()
            return {"content": response.text}
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
