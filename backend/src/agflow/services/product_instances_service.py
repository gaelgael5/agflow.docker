"""Product instances service — filesystem-based.

Each instance lives at {AGFLOW_DATA_DIR}/projects/{project_id}/instances/{id}.json.
The instance ID is derived from project_id + instance_name.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

import structlog

from agflow.schemas.products import InstanceSummary

_log = structlog.get_logger(__name__)


def _projects_dir() -> str:
    return os.path.join(os.environ.get("AGFLOW_DATA_DIR", "/app/data"), "projects")


def _instances_dir(project_id: str) -> str:
    return os.path.join(_projects_dir(), project_id, "instances")


def _instance_path(project_id: str, instance_id: str) -> str:
    return os.path.join(_instances_dir(project_id), f"{instance_id}.json")


def _make_id(project_id: str, instance_name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"instance:{project_id}/{instance_name}"))


def _read(project_id: str, instance_id: str) -> dict[str, Any] | None:
    path = _instance_path(project_id, instance_id)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def _write(project_id: str, instance_id: str, data: dict[str, Any]) -> None:
    d = _instances_dir(project_id)
    os.makedirs(d, exist_ok=True)
    with open(_instance_path(project_id, instance_id), "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))


def _to_summary(instance_id: str, data: dict[str, Any]) -> InstanceSummary:
    return InstanceSummary(
        id=instance_id,
        instance_name=data.get("instance_name", ""),
        catalog_id=data.get("catalog_id", ""),
        project_id=data.get("project_id", ""),
        variables=data.get("variables", {}),
        secret_refs=data.get("secret_refs", {}),
        service_role=data.get("service_role"),
        status=data.get("status", "draft"),
        service_url=data.get("service_url"),
    )


class InstanceNotFoundError(Exception):
    pass


class DuplicateInstanceError(Exception):
    pass


def list_for_project(project_id: str) -> list[InstanceSummary]:
    d = _instances_dir(project_id)
    if not os.path.isdir(d):
        return []
    results = []
    for fname in sorted(os.listdir(d)):
        if not fname.endswith(".json"):
            continue
        iid = fname[:-5]
        data = _read(project_id, iid)
        if data:
            results.append(_to_summary(iid, data))
    return results


def list_all() -> list[InstanceSummary]:
    pd = _projects_dir()
    if not os.path.isdir(pd):
        return []
    results = []
    for project_name in sorted(os.listdir(pd)):
        results.extend(list_for_project(project_name))
    return results


def get_by_id(project_id: str, instance_id: str) -> InstanceSummary:
    data = _read(project_id, instance_id)
    if data is None:
        raise InstanceNotFoundError(f"Instance '{instance_id}' not found in project '{project_id}'")
    return _to_summary(instance_id, data)


def create(
    instance_name: str,
    catalog_id: str,
    project_id: str,
    variables: dict[str, str] | None = None,
    secret_refs: dict[str, str] | None = None,
    service_role: str | None = None,
) -> InstanceSummary:
    instance_id = _make_id(project_id, instance_name)
    if _read(project_id, instance_id) is not None:
        raise DuplicateInstanceError(f"Instance '{instance_name}' already exists in project '{project_id}'")

    # Verify project exists
    project_dir = os.path.join(_projects_dir(), project_id)
    if not os.path.isdir(project_dir):
        raise InstanceNotFoundError(f"Project '{project_id}' not found")

    data = {
        "instance_name": instance_name,
        "catalog_id": catalog_id,
        "project_id": project_id,
        "variables": variables or {},
        "secret_refs": secret_refs or {},
        "service_role": service_role,
        "status": "draft",
        "service_url": None,
    }
    _write(project_id, instance_id, data)
    _log.info("instances.create", project=project_id, name=instance_name, catalog=catalog_id)
    return _to_summary(instance_id, data)


def update(project_id: str, instance_id: str, **kwargs: Any) -> InstanceSummary:
    data = _read(project_id, instance_id)
    if data is None:
        raise InstanceNotFoundError(f"Instance '{instance_id}' not found")
    for k, v in kwargs.items():
        if v is not None:
            data[k] = v
    _write(project_id, instance_id, data)
    _log.info("instances.update", project=project_id, id=instance_id)
    return _to_summary(instance_id, data)


def delete(project_id: str, instance_id: str) -> None:
    path = _instance_path(project_id, instance_id)
    if not os.path.isfile(path):
        raise InstanceNotFoundError(f"Instance '{instance_id}' not found")
    os.remove(path)
    _log.info("instances.delete", project=project_id, id=instance_id)


def activate(project_id: str, instance_id: str, service_url: str) -> InstanceSummary:
    data = _read(project_id, instance_id)
    if data is None:
        raise InstanceNotFoundError(f"Instance '{instance_id}' not found")
    data["status"] = "active"
    data["service_url"] = service_url
    _write(project_id, instance_id, data)
    _log.info("instances.activate", project=project_id, id=instance_id, url=service_url)
    return _to_summary(instance_id, data)


def stop(project_id: str, instance_id: str) -> InstanceSummary:
    data = _read(project_id, instance_id)
    if data is None:
        raise InstanceNotFoundError(f"Instance '{instance_id}' not found")
    data["status"] = "stopped"
    _write(project_id, instance_id, data)
    _log.info("instances.stop", project=project_id, id=instance_id)
    return _to_summary(instance_id, data)
