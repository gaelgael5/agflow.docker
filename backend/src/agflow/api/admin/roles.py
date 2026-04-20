from __future__ import annotations

import io
import json
import zipfile
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.roles import (
    DocumentCreate,
    DocumentSummary,
    DocumentUpdate,
    RoleCreate,
    RoleDetail,
    RoleSummary,
    RoleUpdate,
    SectionCreate,
    SectionSummary,
    SectionWithDocuments,
)
from agflow.services import (
    prompt_generator,
    role_documents_service,
    role_sections_service,
    roles_service,
)

router = APIRouter(
    prefix="/api/admin/roles",
    tags=["admin-roles"],
    dependencies=[Depends(require_admin)],
)


@router.get(
    "",
    response_model=list[RoleSummary],
    summary="List all roles",
    description="Returns all agent roles as a list of RoleSummary objects, including their id, display name, description, and supported service types.",
)
async def list_roles() -> list[RoleSummary]:
    return await roles_service.list_all()


@router.post(
    "",
    response_model=RoleSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a role",
    description="Creates a new agent role. Returns 201 with the RoleSummary on success, 409 if the role id already exists, or 400 if an invalid service type is provided.",
)
async def create_role(payload: RoleCreate) -> RoleSummary:
    try:
        return await roles_service.create(
            role_id=payload.id,
            display_name=payload.display_name,
            description=payload.description,
            service_types=payload.service_types,
            identity_md=payload.identity_md,
        )
    except roles_service.DuplicateRoleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except roles_service.InvalidServiceTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get(
    "/{role_id}",
    response_model=RoleDetail,
    summary="Get role detail with sections and documents",
    description="Returns the full RoleDetail for the given role, including its sections and associated documents grouped by section. Returns 404 if the role does not exist.",
)
async def get_role(role_id: str) -> RoleDetail:
    try:
        role = await roles_service.get_by_id(role_id)
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
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


@router.put(
    "/{role_id}",
    response_model=RoleSummary,
    summary="Update a role",
    description="Partially updates the given role (display name, description, identity markdown, service types). Returns the updated RoleSummary, 404 if not found, or 400 if an invalid service type is provided.",
)
async def update_role(role_id: str, payload: RoleUpdate) -> RoleSummary:
    try:
        return await roles_service.update(
            role_id, **payload.model_dump(exclude_unset=True)
        )
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except roles_service.InvalidServiceTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a role",
    description="Permanently deletes the role and all its associated sections and documents. Returns 204 on success, or 404 if the role does not exist.",
)
async def delete_role(role_id: str) -> None:
    try:
        await roles_service.delete(role_id)
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get(
    "/{role_id}/export",
    summary="Export a role as a ZIP archive",
    description="Builds an in-memory ZIP containing role.json (metadata + sections) and one Markdown file per document, then streams it as a download. Returns 404 if the role does not exist.",
)
async def export_role(role_id: str) -> StreamingResponse:
    try:
        role = await roles_service.get_by_id(role_id)
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    sections = await role_sections_service.list_for_role(role_id)
    documents = await role_documents_service.list_for_role(role_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        meta = {
            "id": role.id,
            "display_name": role.display_name,
            "description": role.description,
            "identity_md": role.identity_md,
            "service_types": role.service_types,
            "sections": [
                {"name": s.name, "display_name": s.display_name, "is_native": s.is_native, "position": s.position}
                for s in sections
            ],
        }
        zf.writestr("role.json", json.dumps(meta, ensure_ascii=False, indent=2))
        for doc in documents:
            zf.writestr(f"{doc.section}/{doc.name}.md", doc.content_md)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{role_id}.zip"'},
    )


@router.post(
    "/{role_id}/import",
    summary="Import role content from a ZIP archive",
    description="Reads a ZIP produced by the export endpoint and upserts all documents into the existing role. Role metadata (display name, description, identity) is updated when present in role.json. Returns the updated RoleDetail, or 404 if the role does not exist.",
)
async def import_role(role_id: str, file: UploadFile = File(...)) -> RoleDetail:
    try:
        await roles_service.get_by_id(role_id)
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    data = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, "Invalid zip file") from exc

    meta = {}
    if "role.json" in zf.namelist():
        meta = json.loads(zf.read("role.json"))

    if meta.get("identity_md") is not None or meta.get("description") is not None:
        updates = {}
        if "identity_md" in meta:
            updates["identity_md"] = meta["identity_md"]
        if "description" in meta:
            updates["description"] = meta["description"]
        if "display_name" in meta:
            updates["display_name"] = meta["display_name"]
        if updates:
            await roles_service.update(role_id, **updates)

    existing_docs = await role_documents_service.list_for_role(role_id)
    existing_by_key = {(d.section, d.name): d for d in existing_docs}

    for info in zf.infolist():
        if info.is_dir() or info.filename == "role.json":
            continue
        parts = info.filename.split("/", 1)
        if len(parts) != 2 or not parts[1].endswith(".md"):
            continue
        section = parts[0]
        doc_name = parts[1][:-3]
        content = zf.read(info).decode("utf-8")

        existing = existing_by_key.get((section, doc_name))
        if existing:
            await role_documents_service.update(existing.id, content_md=content)
        else:
            sections = await role_sections_service.list_for_role(role_id)
            if not any(s.name == section for s in sections):
                await role_sections_service.create(role_id, name=section, display_name=section.capitalize())
            await role_documents_service.create(
                role_id=role_id, section=section, name=doc_name, content_md=content,
            )

    return await get_role(role_id)


@router.post(
    "/{role_id}/generate-prompts",
    response_model=RoleSummary,
    summary="Generate orchestrator prompt from role documents",
    description="Calls Anthropic Claude to synthesize all role documents and sections into a prompt_orchestrator_md field, then persists it on the role. Returns 404 if not found, or 412 if the ANTHROPIC_API_KEY secret is missing.",
)
async def generate_prompts_endpoint(role_id: str) -> RoleSummary:
    try:
        role = await roles_service.get_by_id(role_id)
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    documents = await role_documents_service.list_for_role(role_id)
    sections = await role_sections_service.list_for_role(role_id)
    try:
        generated = await prompt_generator.generate_prompts(
            role, documents, sections
        )
    except prompt_generator.MissingAnthropicKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED, detail=str(exc)
        ) from exc

    return await roles_service.update_prompts(
        role_id,
        prompt_orchestrator_md=generated.prompt_orchestrator_md,
    )


@router.get(
    "/{role_id}/documents",
    response_model=list[DocumentSummary],
    summary="List documents for a role",
    description="Returns all documents belonging to the specified role as a list of DocumentSummary objects, ordered by section and position.",
)
async def list_documents(role_id: str) -> list[DocumentSummary]:
    return await role_documents_service.list_for_role(role_id)


@router.post(
    "/{role_id}/documents",
    response_model=DocumentSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a document in a role",
    description="Adds a new Markdown document to the specified role under the given section. Returns 201 with the DocumentSummary, or 409 if a document with the same name already exists in that section.",
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


@router.put(
    "/{role_id}/documents/{doc_id}",
    response_model=DocumentSummary,
    summary="Update a document",
    description="Updates the name, Markdown content, and/or protected flag of a document. Returns the updated DocumentSummary, 404 if not found, or 403 if the document is protected.",
)
async def update_document(
    role_id: str, doc_id: UUID, payload: DocumentUpdate
) -> DocumentSummary:
    try:
        return await role_documents_service.update(
            doc_id, name=payload.name, content_md=payload.content_md, protected=payload.protected
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
    "/{role_id}/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
    description="Permanently deletes the specified document. Returns 204 on success, 404 if not found, or 403 if the document is protected and cannot be deleted.",
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


@router.get(
    "/{role_id}/sections",
    response_model=list[SectionSummary],
    summary="List sections for a role",
    description="Returns all sections belonging to the specified role as a list of SectionSummary objects. Returns 404 if the role does not exist.",
)
async def list_sections(role_id: str) -> list[SectionSummary]:
    try:
        await roles_service.get_by_id(role_id)
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return await role_sections_service.list_for_role(role_id)


@router.post(
    "/{role_id}/sections",
    response_model=SectionSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a section in a role",
    description="Adds a new section to the specified role. Returns 201 with the SectionSummary, 404 if the role does not exist, or 409 if a section with the same name already exists.",
)
async def create_section(
    role_id: str, payload: SectionCreate
) -> SectionSummary:
    try:
        await roles_service.get_by_id(role_id)
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    try:
        return await role_sections_service.create(
            role_id=role_id, name=payload.name, display_name=payload.display_name
        )
    except role_sections_service.DuplicateSectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.delete(
    "/{role_id}/sections/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a section from a role",
    description="Permanently deletes the named section. Returns 204 on success, 404 if not found, 403 if the section is native/protected, or 409 if the section still contains documents.",
)
async def delete_section(role_id: str, name: str) -> None:
    try:
        await role_sections_service.delete(role_id, name)
    except role_sections_service.SectionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except role_sections_service.ProtectedSectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except role_sections_service.SectionNotEmptyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
