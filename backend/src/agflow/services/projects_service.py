"""Projects service — filesystem-based.

Each project lives at {AGFLOW_DATA_DIR}/projects/{id}/project.json.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Any

import structlog

from agflow.schemas.products import ProjectSummary

_log = structlog.get_logger(__name__)


def _projects_dir() -> str:
    return os.path.join(os.environ.get("AGFLOW_DATA_DIR", "/app/data"), "projects")


def _project_dir(project_id: str) -> str:
    return os.path.join(_projects_dir(), project_id)


def _project_path(project_id: str) -> str:
    return os.path.join(_project_dir(project_id), "project.json")


def _read(project_id: str) -> dict[str, Any] | None:
    path = _project_path(project_id)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def _write(project_id: str, data: dict[str, Any]) -> None:
    d = _project_dir(project_id)
    os.makedirs(d, exist_ok=True)
    with open(_project_path(project_id), "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))


def _to_summary(project_id: str, data: dict[str, Any]) -> ProjectSummary:
    return ProjectSummary(
        id=project_id,
        display_name=data.get("display_name", project_id),
        description=data.get("description", ""),
        environment=data.get("environment", "dev"),
        tags=data.get("tags", []),
    )


class ProjectNotFoundError(Exception):
    pass


class DuplicateProjectError(Exception):
    pass


def list_all() -> list[ProjectSummary]:
    d = _projects_dir()
    if not os.path.isdir(d):
        return []
    results = []
    for name in sorted(os.listdir(d)):
        data = _read(name)
        if data:
            results.append(_to_summary(name, data))
    return results


def get_by_id(project_id: str) -> ProjectSummary:
    data = _read(project_id)
    if data is None:
        raise ProjectNotFoundError(f"Project '{project_id}' not found")
    return _to_summary(project_id, data)


def create(
    project_id: str,
    display_name: str,
    description: str = "",
    environment: str = "dev",
    tags: list[str] | None = None,
) -> ProjectSummary:
    if _read(project_id) is not None:
        raise DuplicateProjectError(f"Project '{project_id}' already exists")
    data = {
        "display_name": display_name,
        "description": description,
        "environment": environment,
        "tags": tags or [],
    }
    _write(project_id, data)
    _log.info("projects.create", id=project_id)
    return _to_summary(project_id, data)


def update(project_id: str, **kwargs: Any) -> ProjectSummary:
    data = _read(project_id)
    if data is None:
        raise ProjectNotFoundError(f"Project '{project_id}' not found")
    for k, v in kwargs.items():
        if v is not None:
            data[k] = v
    _write(project_id, data)
    _log.info("projects.update", id=project_id)
    return _to_summary(project_id, data)


def delete(project_id: str) -> None:
    d = _project_dir(project_id)
    if not os.path.isdir(d):
        raise ProjectNotFoundError(f"Project '{project_id}' not found")
    shutil.rmtree(d)
    _log.info("projects.delete", id=project_id)
