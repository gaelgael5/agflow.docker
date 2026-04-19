"""Product backends service — filesystem-based.

Each backend lives at {AGFLOW_DATA_DIR}/projects/{project_id}/backends/{instance_id}.json.
Created when an instance is activated, removed when stopped.
"""
from __future__ import annotations

import json
import os
from typing import Any

import structlog

_log = structlog.get_logger(__name__)


def _projects_dir() -> str:
    return os.path.join(os.environ.get("AGFLOW_DATA_DIR", "/app/data"), "projects")


def _backends_dir(project_id: str) -> str:
    return os.path.join(_projects_dir(), project_id, "backends")


def _backend_path(project_id: str, instance_id: str) -> str:
    return os.path.join(_backends_dir(project_id), f"{instance_id}.json")


class BackendNotFoundError(Exception):
    pass


def get(project_id: str, instance_id: str) -> dict[str, Any] | None:
    path = _backend_path(project_id, instance_id)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def save(project_id: str, instance_id: str, data: dict[str, Any]) -> None:
    d = _backends_dir(project_id)
    os.makedirs(d, exist_ok=True)
    with open(_backend_path(project_id, instance_id), "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))
    _log.info("backends.save", project=project_id, instance=instance_id)


def delete(project_id: str, instance_id: str) -> None:
    path = _backend_path(project_id, instance_id)
    if os.path.isfile(path):
        os.remove(path)
        _log.info("backends.delete", project=project_id, instance=instance_id)


def list_for_project(project_id: str) -> list[dict[str, Any]]:
    d = _backends_dir(project_id)
    if not os.path.isdir(d):
        return []
    results = []
    for fname in sorted(os.listdir(d)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(d, fname), encoding="utf-8") as f:
            data = json.loads(f.read())
            data["instance_id"] = fname[:-5]
            results.append(data)
    return results
