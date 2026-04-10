from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.roles import DocumentSummary, Section

_log = structlog.get_logger(__name__)

_DOC_COLS = (
    "id, role_id, section, parent_path, name, content_md, protected, "
    "created_at, updated_at"
)


class DocumentNotFoundError(Exception):
    pass


class DuplicateDocumentError(Exception):
    pass


class ProtectedDocumentError(Exception):
    pass


def _row(row: dict) -> DocumentSummary:
    return DocumentSummary(**row)


async def create(
    role_id: str,
    section: Section,
    name: str,
    parent_path: str = "",
    content_md: str = "",
    protected: bool = False,
) -> DocumentSummary:
    try:
        row = await fetch_one(
            f"""
            INSERT INTO role_documents (
                role_id, section, parent_path, name, content_md, protected
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING {_DOC_COLS}
            """,
            role_id,
            section,
            parent_path,
            name,
            content_md,
            protected,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateDocumentError(
            f"Document '{name}' already exists in {section} for role '{role_id}'"
        ) from exc
    assert row is not None
    _log.info(
        "role_documents.create", role_id=role_id, section=section, name=name
    )
    return _row(row)


async def get_by_id(doc_id: UUID) -> DocumentSummary:
    row = await fetch_one(
        f"SELECT {_DOC_COLS} FROM role_documents WHERE id = $1", doc_id
    )
    if row is None:
        raise DocumentNotFoundError(f"Document {doc_id} not found")
    return _row(row)


async def list_for_role(role_id: str) -> list[DocumentSummary]:
    rows = await fetch_all(
        f"""
        SELECT {_DOC_COLS} FROM role_documents
        WHERE role_id = $1
        ORDER BY section ASC, parent_path ASC, name ASC
        """,
        role_id,
    )
    return [_row(r) for r in rows]


async def update(
    doc_id: UUID,
    content_md: str | None = None,
    protected: bool | None = None,
) -> DocumentSummary:
    current = await get_by_id(doc_id)

    if current.protected and content_md is not None:
        raise ProtectedDocumentError(
            f"Document '{current.name}' is protected; unlock it first"
        )

    sets: list[str] = []
    args: list[object] = []
    idx = 1
    if content_md is not None:
        sets.append(f"content_md = ${idx}")
        args.append(content_md)
        idx += 1
    if protected is not None:
        sets.append(f"protected = ${idx}")
        args.append(protected)
        idx += 1
    if not sets:
        return current
    sets.append("updated_at = NOW()")
    args.append(doc_id)

    row = await fetch_one(
        f"""
        UPDATE role_documents SET {", ".join(sets)}
        WHERE id = ${idx}
        RETURNING {_DOC_COLS}
        """,
        *args,
    )
    assert row is not None
    _log.info("role_documents.update", doc_id=str(doc_id))
    return _row(row)


async def delete(doc_id: UUID) -> None:
    current = await get_by_id(doc_id)
    if current.protected:
        raise ProtectedDocumentError(
            f"Document '{current.name}' is protected; unlock it first"
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM role_documents WHERE id = $1", doc_id)
    _log.info("role_documents.delete", doc_id=str(doc_id))
