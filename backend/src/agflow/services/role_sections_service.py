from __future__ import annotations

import os

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one, get_pool
from agflow.schemas.roles import NATIVE_SECTIONS, SectionSummary

_log = structlog.get_logger(__name__)

_COLS = "role_id, name, display_name, is_native, position, created_at"

# Native sections with their default French display names and positions.
_NATIVE_DEFAULTS: list[tuple[str, str, int]] = [
    ("roles", "Rôles", 0),
    ("missions", "Missions", 1),
    ("competences", "Compétences", 2),
]


class SectionNotFoundError(Exception):
    pass


class DuplicateSectionError(Exception):
    pass


class ProtectedSectionError(Exception):
    """Raised when attempting to delete a native section."""


class SectionNotEmptyError(Exception):
    """Raised when attempting to delete a section that still has documents."""


def _row(row: dict) -> SectionSummary:
    return SectionSummary(
        name=row["name"],
        display_name=row["display_name"],
        is_native=row["is_native"],
        position=row["position"],
    )


async def seed_natives(role_id: str) -> None:
    """Insert the 3 native sections for a freshly created role."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        for name, display_name, position in _NATIVE_DEFAULTS:
            await conn.execute(
                """
                INSERT INTO role_sections
                    (role_id, name, display_name, is_native, position)
                VALUES ($1, $2, $3, TRUE, $4)
                ON CONFLICT (role_id, name) DO NOTHING
                """,
                role_id,
                name,
                display_name,
                position,
            )
    _log.info("role_sections.seed_natives", role_id=role_id)


async def list_for_role(role_id: str) -> list[SectionSummary]:
    rows = await fetch_all(
        f"""
        SELECT {_COLS}
        FROM role_sections
        WHERE role_id = $1
        ORDER BY position ASC, name ASC
        """,
        role_id,
    )
    return [_row(r) for r in rows]


async def get(role_id: str, name: str) -> SectionSummary:
    row = await fetch_one(
        f"SELECT {_COLS} FROM role_sections WHERE role_id = $1 AND name = $2",
        role_id,
        name,
    )
    if row is None:
        raise SectionNotFoundError(
            f"Section '{name}' not found for role '{role_id}'"
        )
    return _row(row)


async def create(
    role_id: str, name: str, display_name: str
) -> SectionSummary:
    existing = await list_for_role(role_id)
    next_position = max((s.position for s in existing), default=-1) + 1
    try:
        row = await fetch_one(
            f"""
            INSERT INTO role_sections
                (role_id, name, display_name, is_native, position)
            VALUES ($1, $2, $3, FALSE, $4)
            RETURNING {_COLS}
            """,
            role_id,
            name,
            display_name,
            next_position,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateSectionError(
            f"Section '{name}' already exists for role '{role_id}'"
        ) from exc
    assert row is not None
    _log.info("role_sections.create", role_id=role_id, name=name)
    return _row(row)


async def delete(role_id: str, name: str) -> None:
    section = await get(role_id, name)
    if section.is_native or name in NATIVE_SECTIONS:
        raise ProtectedSectionError(
            f"Native section '{name}' cannot be deleted"
        )
    # role_documents are now filesystem-based (under AGFLOW_DATA_DIR/roles/<id>/<section>/),
    # so we count .md files in the section directory instead of querying the
    # old role_documents table.
    base = os.environ.get("AGFLOW_DATA_DIR", "/app/data")
    section_dir = os.path.join(base, "roles", role_id, name)
    doc_count = 0
    if os.path.isdir(section_dir):
        doc_count = sum(1 for f in os.listdir(section_dir) if f.endswith(".md"))
    if doc_count > 0:
        raise SectionNotEmptyError(
            f"Section '{name}' still has {doc_count} document(s)"
        )
    result = await execute(
        "DELETE FROM role_sections WHERE role_id = $1 AND name = $2",
        role_id,
        name,
    )
    if result == "DELETE 0":
        raise SectionNotFoundError(
            f"Section '{name}' not found for role '{role_id}'"
        )
    _log.info("role_sections.delete", role_id=role_id, name=name)
