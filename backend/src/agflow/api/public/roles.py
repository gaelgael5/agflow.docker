from __future__ import annotations

from fastapi import APIRouter

from agflow.auth.api_key import require_api_key
from agflow.schemas.roles import RoleDetail, RoleSummary, SectionWithDocuments
from agflow.services import role_documents_service, role_sections_service, roles_service

router = APIRouter(prefix="/api/v1", tags=["public-roles"])


@router.get("/roles", response_model=list[RoleSummary])
async def list_roles(
    _key: dict = require_api_key("roles:read"),
) -> list[RoleSummary]:
    return await roles_service.list_all()


@router.get("/roles/{role_id}", response_model=RoleDetail)
async def get_role(
    role_id: str,
    _key: dict = require_api_key("roles:read"),
) -> RoleDetail:
    role = await roles_service.get_by_id(role_id)
    sections = await role_sections_service.list_for_role(role_id)
    documents = await role_documents_service.list_for_role(role_id)
    sections_with_docs = [
        SectionWithDocuments(
            **s.model_dump(),
            documents=[d for d in documents if d.section == s.name],
        )
        for s in sections
    ]
    return RoleDetail(role=role, sections=sections_with_docs)
