"""Role filesystem storage.

Each role lives at {AGFLOW_DATA_DIR}/roles/{role_id}/ with:
  role.json                ← {display_name, description, service_types}
  identity.md              ← editable identity prompt
  prompt_orchestrator.md   ← auto-generated orchestrator prompt
  {section}/               ← one directory per section
    {document_name}.md     ← document content
"""
from __future__ import annotations

import json
import os
from typing import Any

import structlog

_log = structlog.get_logger(__name__)


def _data_dir() -> str:
    return os.environ.get("AGFLOW_DATA_DIR", "/app/data")


def _role_dir(role_id: str) -> str:
    return os.path.join(_data_dir(), "roles", role_id)


# ── Role metadata ────────────────────────────────────────────────────────────


def read_meta(role_id: str) -> dict[str, Any]:
    path = os.path.join(_role_dir(role_id), "role.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def write_meta(role_id: str, meta: dict[str, Any]) -> None:
    d = _role_dir(role_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "role.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False, indent=2))


def read_identity(role_id: str) -> str:
    path = os.path.join(_role_dir(role_id), "identity.md")
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_identity(role_id: str, content: str) -> None:
    d = _role_dir(role_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "identity.md"), "w", encoding="utf-8") as f:
        f.write(content)


def read_prompt_orchestrator(role_id: str) -> str:
    path = os.path.join(_role_dir(role_id), "prompt_orchestrator.md")
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_prompt_orchestrator(role_id: str, content: str) -> None:
    d = _role_dir(role_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "prompt_orchestrator.md"), "w", encoding="utf-8") as f:
        f.write(content)


# ── Documents ────────────────────────────────────────────────────────────────


def read_document(role_id: str, section: str, name: str) -> str:
    path = os.path.join(_role_dir(role_id), section, f"{name}.md")
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_document(role_id: str, section: str, name: str, content: str) -> None:
    d = os.path.join(_role_dir(role_id), section)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write(content)


def delete_document(role_id: str, section: str, name: str) -> None:
    path = os.path.join(_role_dir(role_id), section, f"{name}.md")
    if os.path.isfile(path):
        os.unlink(path)
    # Clean empty section dir
    section_dir = os.path.join(_role_dir(role_id), section)
    if os.path.isdir(section_dir) and not os.listdir(section_dir):
        os.rmdir(section_dir)


def rename_document(
    role_id: str, section: str, old_name: str, new_name: str
) -> None:
    old_path = os.path.join(_role_dir(role_id), section, f"{old_name}.md")
    new_path = os.path.join(_role_dir(role_id), section, f"{new_name}.md")
    if os.path.isfile(old_path):
        os.rename(old_path, new_path)


def delete_role_dir(role_id: str) -> None:
    import shutil

    d = _role_dir(role_id)
    if os.path.isdir(d):
        shutil.rmtree(d)


# ── Migration ────────────────────────────────────────────────────────────────


async def migrate_db_to_disk() -> None:
    """One-time migration: read role content from DB and write to disk."""
    from agflow.db.pool import fetch_all

    try:
        rows = await fetch_all(
            "SELECT id, display_name, description, service_types, "
            "identity_md, prompt_orchestrator_md FROM roles"
        )
    except Exception as exc:
        _log.warning("role_files.migrate.skip", reason=str(exc))
        return

    migrated = 0
    for row in rows:
        role_id = row["id"]
        d = _role_dir(role_id)
        if os.path.isfile(os.path.join(d, "role.json")):
            continue
        write_meta(role_id, {
            "display_name": row["display_name"],
            "description": row["description"],
            "service_types": list(row["service_types"] or []),
        })
        write_identity(role_id, row["identity_md"] or "")
        write_prompt_orchestrator(role_id, row["prompt_orchestrator_md"] or "")
        migrated += 1

    # Migrate documents
    try:
        docs = await fetch_all(
            "SELECT role_id, section, name, content_md FROM role_documents"
        )
    except Exception:
        docs = []

    doc_migrated = 0
    for doc in docs:
        path = os.path.join(
            _role_dir(doc["role_id"]), doc["section"], f"{doc['name']}.md"
        )
        if os.path.isfile(path):
            continue
        write_document(doc["role_id"], doc["section"], doc["name"], doc["content_md"] or "")
        doc_migrated += 1

    _log.info(
        "role_files.migrate.done",
        roles=migrated,
        documents=doc_migrated,
    )
