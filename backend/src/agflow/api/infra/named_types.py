from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.infra import (
    NamedTypeCreate,
    NamedTypeRow,
    NamedTypeUpdate,
)
from agflow.schemas.infra_env_vars import (
    NamedTypeEnvVarCreate,
    NamedTypeEnvVarRow,
    NamedTypeEnvVarUpdate,
)
from agflow.services import infra_env_vars_service, infra_named_types_service

router = APIRouter(
    prefix="/api/infra/named-types",
    tags=["infra-named-types"],
)

_admin = [Depends(require_admin)]


@router.get("", response_model=list[NamedTypeRow], dependencies=_admin)
async def list_named_types():
    return await infra_named_types_service.list_all()


@router.post(
    "", response_model=NamedTypeRow, status_code=status.HTTP_201_CREATED, dependencies=_admin,
)
async def create_named_type(payload: NamedTypeCreate):
    return await infra_named_types_service.create(
        name=payload.name,
        type_id=payload.type_id,
        sub_type_id=payload.sub_type_id,
        connection_type=payload.connection_type,
    )


@router.get("/{named_type_id}", response_model=NamedTypeRow, dependencies=_admin)
async def get_named_type(named_type_id: UUID):
    try:
        return await infra_named_types_service.get_by_id(named_type_id)
    except infra_named_types_service.NamedTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{named_type_id}", response_model=NamedTypeRow, dependencies=_admin)
async def update_named_type(named_type_id: UUID, payload: NamedTypeUpdate):
    try:
        return await infra_named_types_service.update(
            named_type_id, **payload.model_dump(exclude_unset=True),
        )
    except infra_named_types_service.NamedTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{named_type_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_admin)
async def delete_named_type(named_type_id: UUID):
    try:
        await infra_named_types_service.delete(named_type_id)
    except infra_named_types_service.NamedTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Env vars du contrat (variante typée) ──────────────────────────────────

@router.get("/{named_type_id}/env-vars", response_model=list[NamedTypeEnvVarRow], dependencies=_admin)
async def list_named_type_env_vars(named_type_id: UUID):
    return await infra_env_vars_service.list_by_named_type(named_type_id)


@router.post(
    "/{named_type_id}/env-vars",
    response_model=NamedTypeEnvVarRow,
    status_code=status.HTTP_201_CREATED,
    dependencies=_admin,
)
async def create_named_type_env_var(named_type_id: UUID, payload: NamedTypeEnvVarCreate):
    try:
        return await infra_env_vars_service.create_env_var(
            named_type_id,
            name=payload.name,
            description=payload.description,
            position=payload.position,
            is_secret=payload.is_secret,
        )
    except infra_env_vars_service.EnvVarDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put(
    "/{named_type_id}/env-vars/{env_var_id}",
    response_model=NamedTypeEnvVarRow,
    dependencies=_admin,
)
async def update_named_type_env_var(named_type_id: UUID, env_var_id: UUID, payload: NamedTypeEnvVarUpdate):
    try:
        return await infra_env_vars_service.update_env_var(
            env_var_id, **payload.model_dump(exclude_unset=True),
        )
    except infra_env_vars_service.EnvVarNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except infra_env_vars_service.EnvVarDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete(
    "/{named_type_id}/env-vars/{env_var_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_admin,
)
async def delete_named_type_env_var(named_type_id: UUID, env_var_id: UUID):
    try:
        await infra_env_vars_service.delete_env_var(env_var_id)
    except infra_env_vars_service.EnvVarNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
