"""Read-only endpoint serving the cross-app launcher menu (apps.json).

The file is mounted into the backend container via docker-compose
(``./apps.json:/app/apps.json:ro``). Path overridable via env
``AGFLOW_APPS_FILE``. Returns ``{"urls": []}`` if the file is missing
or invalid — so the TopBar hamburger menu silently degrades when no
launcher is configured (single-app dev setups).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, HttpUrl

from agflow.auth.dependencies import require_operator as require_admin

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/apps",
    tags=["admin-apps"],
    dependencies=[Depends(require_admin)],
)


class AppEntry(BaseModel):
    key: str
    label: str
    icon: str = ""
    url: HttpUrl


class AppsResponse(BaseModel):
    urls: list[AppEntry]


def _apps_file() -> Path:
    return Path(os.environ.get("AGFLOW_APPS_FILE", "/app/apps.json"))


@router.get("", response_model=AppsResponse, summary="Cross-app launcher menu")
async def list_apps(_email: Annotated[str, Depends(require_admin)]) -> AppsResponse:
    """Return the apps.json content.

    Empty list if the file is missing or its JSON is invalid — the TopBar
    menu just won't render in that case.
    """
    path = _apps_file()
    if not path.is_file():
        return AppsResponse(urls=[])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("apps.read_failed", path=str(path), error=str(exc))
        return AppsResponse(urls=[])
    return AppsResponse(urls=raw.get("urls", []))
