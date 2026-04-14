"""Role documents — fully filesystem-based.

Documents live at {AGFLOW_DATA_DIR}/roles/{role_id}/{section}/{name}.md.
IDs are deterministic UUID5 based on (role_id, section, name).
The `protected` flag is encoded as a trailing `_` in the filename.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from uuid import UUID

import structlog

from agflow.schemas.roles import DocumentSummary, Section
from agflow.services import role_files_service

_log = structlog.get_logger(__name__)

_DOC_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _doc_id(role_id: str, section: str, name: str) -> UUID:
    return uuid.uuid5(_DOC_NS, f"{role_id}:{section}:{name}")


class DocumentNotFoundError(Exception):
    pass


class DuplicateDocumentError(Exception):
    pass


class ProtectedDocumentError(Exception):
    pass


def _role_dir(role_id: str) -> str:
    base = os.environ.get("AGFLOW_DATA_DIR", "/app/data")
    return os.path.join(base, "roles", role_id)


def _file_to_summary(role_id: str, section: str, filename: str) -> DocumentSummary:
    """Convert a .md file on disk to a DocumentSummary."""
    name = filename[:-3]  # strip .md
    content = role_files_service.read_document(role_id, section, name)
    full_path = os.path.join(_role_dir(role_id), section, filename)
    try:
        mtime = os.path.getmtime(full_path)
        ctime = os.path.getctime(full_path)
    except OSError:
        mtime = ctime = 0
    return DocumentSummary(
        id=_doc_id(role_id, section, name),
        role_id=role_id,
        section=section,
        parent_path="",
        name=name,
        content_md=content,
        protected=name.endswith("_"),
        created_at=datetime.fromtimestamp(ctime, tz=UTC),
        updated_at=datetime.fromtimestamp(mtime, tz=UTC),
    )


async def create(
    role_id: str,
    section: Section,
    name: str,
    parent_path: str = "",
    content_md: str = "",
    protected: bool = False,
) -> DocumentSummary:
    path = os.path.join(_role_dir(role_id), section, f"{name}.md")
    if os.path.isfile(path):
        raise DuplicateDocumentError(
            f"Document '{name}' already exists in {section} for role '{role_id}'"
        )
    role_files_service.write_document(role_id, section, name, content_md)
    _log.info("role_documents.create", role_id=role_id, section=section, name=name)
    return _file_to_summary(role_id, section, f"{name}.md")


async def get_by_id(doc_id: UUID) -> DocumentSummary:
    base = os.environ.get("AGFLOW_DATA_DIR", "/app/data")
    roles_dir = os.path.join(base, "roles")
    if not os.path.isdir(roles_dir):
        raise DocumentNotFoundError(f"Document {doc_id} not found")
    for role_id in os.listdir(roles_dir):
        role_path = os.path.join(roles_dir, role_id)
        if not os.path.isdir(role_path):
            continue
        for section in os.listdir(role_path):
            section_path = os.path.join(role_path, section)
            if not os.path.isdir(section_path):
                continue
            for filename in os.listdir(section_path):
                if not filename.endswith(".md"):
                    continue
                name = filename[:-3]
                if _doc_id(role_id, section, name) == doc_id:
                    return _file_to_summary(role_id, section, filename)
    raise DocumentNotFoundError(f"Document {doc_id} not found")


async def list_for_role(role_id: str) -> list[DocumentSummary]:
    role_path = _role_dir(role_id)
    if not os.path.isdir(role_path):
        return []
    results: list[DocumentSummary] = []
    for section in sorted(os.listdir(role_path)):
        section_path = os.path.join(role_path, section)
        if not os.path.isdir(section_path):
            continue
        # Skip non-section dirs (like "agents")
        if section in (".", ".."):
            continue
        for filename in sorted(os.listdir(section_path)):
            if not filename.endswith(".md"):
                continue
            results.append(_file_to_summary(role_id, section, filename))
    return results


async def update(
    doc_id: UUID,
    name: str | None = None,
    content_md: str | None = None,
    protected: bool | None = None,
) -> DocumentSummary:
    current = await get_by_id(doc_id)

    if current.name.endswith("_") and content_md is not None:
        raise ProtectedDocumentError(
            f"Document '{current.name}' is locked; unlock it first"
        )

    effective_name = current.name

    if name is not None and name != current.name:
        role_files_service.rename_document(
            current.role_id, current.section, current.name, name
        )
        effective_name = name

    if content_md is not None:
        role_files_service.write_document(
            current.role_id, current.section, effective_name, content_md
        )

    _log.info("role_documents.update", doc_id=str(doc_id))
    return _file_to_summary(current.role_id, current.section, f"{effective_name}.md")


async def delete(doc_id: UUID) -> None:
    current = await get_by_id(doc_id)
    if current.name.endswith("_"):
        raise ProtectedDocumentError(
            f"Document '{current.name}' is locked; unlock it first"
        )
    role_files_service.delete_document(current.role_id, current.section, current.name)
    _log.info("role_documents.delete", doc_id=str(doc_id))
