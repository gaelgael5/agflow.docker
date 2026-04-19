"""Types loader — scans data/platforms/ and data/services/ JSON files.

Builds in-memory cache of platform and service definitions.
Validates each file against Pydantic schemas.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import structlog

from agflow.schemas.infra import PlatformDef, ServiceDef

_log = structlog.get_logger(__name__)

_platforms: dict[str, PlatformDef] = {}
_services: dict[str, ServiceDef] = {}


def _data_dir() -> Path:
    data = os.environ.get("AGFLOW_DATA_DIR", "/app/data")
    data_path = Path(data)
    if data_path.is_dir():
        return data_path
    return Path(__file__).parent.parent.parent.parent / "data"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.loads(f.read())
    except Exception as exc:
        _log.warning("types_loader.invalid_json", path=str(path), error=str(exc))
        return None


def reload() -> dict[str, int]:
    """Scan disk and reload cache. Returns counts."""
    global _platforms, _services

    new_platforms: dict[str, PlatformDef] = {}
    new_services: dict[str, ServiceDef] = {}

    # Platforms
    platforms_dir = _data_dir() / "platforms"
    if platforms_dir.is_dir():
        for p in sorted(platforms_dir.glob("*.json")):
            raw = _load_json(p)
            if not raw or "name" not in raw:
                continue
            try:
                pdef = PlatformDef(**raw)
                new_platforms[pdef.name] = pdef
                _log.info("types_loader.platform_loaded", name=pdef.name)
            except Exception as exc:
                _log.warning("types_loader.platform_invalid", path=str(p), error=str(exc))

    # Services
    services_dir = _data_dir() / "services"
    if services_dir.is_dir():
        for s in sorted(services_dir.glob("*.json")):
            raw = _load_json(s)
            if not raw or "name" not in raw:
                continue
            try:
                sdef = ServiceDef(**raw)
                new_services[sdef.name] = sdef
                _log.info("types_loader.service_loaded", name=sdef.name)
            except Exception as exc:
                _log.warning("types_loader.service_invalid", path=str(s), error=str(exc))

    _platforms = new_platforms
    _services = new_services

    _log.info("types_loader.reload_complete",
              platforms=len(_platforms), services=len(_services))

    return {"platforms": len(_platforms), "services": len(_services)}


def get_platforms() -> list[PlatformDef]:
    if not _platforms:
        reload()
    return list(_platforms.values())


def get_platform(name: str) -> PlatformDef | None:
    if not _platforms:
        reload()
    return _platforms.get(name)


def get_services() -> list[ServiceDef]:
    if not _services:
        reload()
    return list(_services.values())


def get_service(name: str) -> ServiceDef | None:
    if not _services:
        reload()
    return _services.get(name)


# ── Write helpers ──────────────────────────────────────────


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "-")


def save_platform(pdef: PlatformDef) -> None:
    """Save platform to disk and update cache."""
    path = _data_dir() / "platforms" / f"{_slugify(pdef.name)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(pdef.model_dump_json(indent=2))
    _platforms[pdef.name] = pdef
    _log.info("types_loader.platform_saved", name=pdef.name, path=str(path))


def delete_platform(name: str) -> None:
    """Delete platform from disk and cache."""
    path = _data_dir() / "platforms" / f"{_slugify(name)}.json"
    if path.exists():
        path.unlink()
    _platforms.pop(name, None)
    _log.info("types_loader.platform_deleted", name=name)


def save_service(sdef: ServiceDef) -> None:
    """Save service to disk and update cache."""
    path = _data_dir() / "services" / f"{_slugify(sdef.name)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(sdef.model_dump_json(indent=2))
    _services[sdef.name] = sdef
    _log.info("types_loader.service_saved", name=sdef.name, path=str(path))


def delete_service(name: str) -> None:
    """Delete service from disk and cache."""
    path = _data_dir() / "services" / f"{_slugify(name)}.json"
    if path.exists():
        path.unlink()
    _services.pop(name, None)
    _log.info("types_loader.service_deleted", name=name)
