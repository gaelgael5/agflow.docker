"""Image registries service — filesystem-based.

Each registry lives at {AGFLOW_DATA_DIR}/registries/{id}.json.
Default registries (docker.io, ghcr.io) are seeded at startup.
"""
from __future__ import annotations

import json
import os
from typing import Any

import structlog

from agflow.schemas.products import RegistrySummary

_log = structlog.get_logger(__name__)


def _registries_dir() -> str:
    return os.path.join(os.environ.get("AGFLOW_DATA_DIR", "/app/data"), "registries")


def _registry_path(registry_id: str) -> str:
    return os.path.join(_registries_dir(), f"{registry_id}.json")


def _read(registry_id: str) -> dict[str, Any] | None:
    path = _registry_path(registry_id)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def _write(registry_id: str, data: dict[str, Any]) -> None:
    d = _registries_dir()
    os.makedirs(d, exist_ok=True)
    with open(_registry_path(registry_id), "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))


def _to_summary(registry_id: str, data: dict[str, Any]) -> RegistrySummary:
    return RegistrySummary(
        id=registry_id,
        display_name=data.get("display_name", registry_id),
        url=data.get("url", ""),
        auth_type=data.get("auth_type", "none"),
        credential_ref=data.get("credential_ref"),
        is_default=data.get("is_default", False),
    )


class RegistryNotFoundError(Exception):
    pass


class DuplicateRegistryError(Exception):
    pass


def seed_defaults() -> None:
    """Create default registries if they don't exist."""
    defaults = [
        {"id": "docker-io", "display_name": "Docker Hub", "url": "https://docker.io", "is_default": True},
        {"id": "ghcr-io", "display_name": "GitHub Container Registry", "url": "https://ghcr.io", "is_default": True},
    ]
    for d in defaults:
        if _read(d["id"]) is None:
            _write(d["id"], {
                "display_name": d["display_name"],
                "url": d["url"],
                "auth_type": "none",
                "is_default": True,
            })
            _log.info("registries.seed", id=d["id"])


def list_all() -> list[RegistrySummary]:
    d = _registries_dir()
    if not os.path.isdir(d):
        return []
    results = []
    for fname in sorted(os.listdir(d)):
        if not fname.endswith(".json"):
            continue
        rid = fname[:-5]
        data = _read(rid)
        if data:
            results.append(_to_summary(rid, data))
    # Defaults first
    results.sort(key=lambda r: (not r.is_default, r.display_name))
    return results


def get_by_id(registry_id: str) -> RegistrySummary:
    data = _read(registry_id)
    if data is None:
        raise RegistryNotFoundError(f"Registry '{registry_id}' not found")
    return _to_summary(registry_id, data)


def create(
    registry_id: str,
    display_name: str,
    url: str,
    auth_type: str = "none",
    credential_ref: str | None = None,
) -> RegistrySummary:
    if _read(registry_id) is not None:
        raise DuplicateRegistryError(f"Registry '{registry_id}' already exists")
    data = {
        "display_name": display_name,
        "url": url,
        "auth_type": auth_type,
        "credential_ref": credential_ref,
        "is_default": False,
    }
    _write(registry_id, data)
    _log.info("registries.create", id=registry_id)
    return _to_summary(registry_id, data)


def update(registry_id: str, **kwargs: Any) -> RegistrySummary:
    data = _read(registry_id)
    if data is None:
        raise RegistryNotFoundError(f"Registry '{registry_id}' not found")
    for k, v in kwargs.items():
        if v is not None:
            data[k] = v
    _write(registry_id, data)
    _log.info("registries.update", id=registry_id)
    return _to_summary(registry_id, data)


def delete(registry_id: str) -> None:
    data = _read(registry_id)
    if data is None:
        raise RegistryNotFoundError(f"Registry '{registry_id}' not found")
    if data.get("is_default"):
        raise RegistryNotFoundError("Cannot delete default registry")
    os.remove(_registry_path(registry_id))
    _log.info("registries.delete", id=registry_id)
