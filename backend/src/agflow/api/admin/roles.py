from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.roles import (
    DocumentCreate,
    DocumentSummary,
    DocumentUpdate,
    RoleCreate,
    RoleDetail,
    RoleSummary,
    RoleUpdate,
)
from agflow.services import prompt_generator, role_documents_service, roles_service

router = APIRouter(
    prefix="/api/admin/roles",
    tags=["admin-roles"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[RoleSummary])
async def list_roles() -> list[RoleSummary]:
    return await roles_service.list_all()


@router.post("", response_model=RoleSummary, status_code=status.HTTP_201_CREATED)
async def create_role(payload: RoleCreate) -> RoleSummary:
    try:
        return await roles_service.create(
            role_id=payload.id,
            display_name=payload.display_name,
            description=payload.description,
            llm_type=payload.llm_type,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            service_types=payload.service_types,
            identity_md=payload.identity_md,
        )
    except roles_service.DuplicateRoleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get("/{role_id}", response_model=RoleDetail)
async def get_role(role_id: str) -> RoleDetail:
    try:
        role = await roles_service.get_by_id(role_id)
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    documents = await role_documents_service.list_for_role(role_id)
    return RoleDetail(
        role=role,
        roles_documents=[d for d in documents if d.section == "roles"],
        missions_documents=[d for d in documents if d.section == "missions"],
        competences_documents=[d for d in documents if d.section == "competences"],
    )


@router.put("/{role_id}", response_model=RoleSummary)
async def update_role(role_id: str, payload: RoleUpdate) -> RoleSummary:
    try:
        return await roles_service.update(
            role_id, **payload.model_dump(exclude_unset=True)
        )
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: str) -> None:
    try:
        await roles_service.delete(role_id)
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/{role_id}/generate-prompts", response_model=RoleSummary)
async def generate_prompts_endpoint(role_id: str) -> RoleSummary:
    try:
        role = await roles_service.get_by_id(role_id)
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    documents = await role_documents_service.list_for_role(role_id)
    try:
        generated = await prompt_generator.generate_prompts(role, documents)
    except prompt_generator.MissingAnthropicKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED, detail=str(exc)
        ) from exc

    return await roles_service.update_prompts(
        role_id,
        prompt_agent_md=generated.prompt_agent_md,
        prompt_orchestrator_md=generated.prompt_orchestrator_md,
    )


@router.get("/{role_id}/documents", response_model=list[DocumentSummary])
async def list_documents(role_id: str) -> list[DocumentSummary]:
    return await role_documents_service.list_for_role(role_id)


@router.post(
    "/{role_id}/documents",
    response_model=DocumentSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(role_id: str, payload: DocumentCreate) -> DocumentSummary:
    try:
        return await role_documents_service.create(
            role_id=role_id,
            section=payload.section,
            name=payload.name,
            content_md=payload.content_md,
            protected=payload.protected,
        )
    except role_documents_service.DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.put("/{role_id}/documents/{doc_id}", response_model=DocumentSummary)
async def update_document(
    role_id: str, doc_id: UUID, payload: DocumentUpdate
) -> DocumentSummary:
    try:
        return await role_documents_service.update(
            doc_id, content_md=payload.content_md, protected=payload.protected
        )
    except role_documents_service.DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except role_documents_service.ProtectedDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc


@router.delete(
    "/{role_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_document(role_id: str, doc_id: UUID) -> None:
    try:
        await role_documents_service.delete(doc_id)
    except role_documents_service.DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except role_documents_service.ProtectedDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
