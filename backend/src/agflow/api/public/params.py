from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from agflow.api.public.errors import api_error
from agflow.auth.api_key import require_api_key
from agflow.services import dockerfile_files_service

router = APIRouter(
    prefix="/api/v1/dockerfiles/{dockerfile_id}/params",
    tags=["public-params"],
)

_DOCKER_SECTIONS = {"Container", "Network", "Runtime", "Resources", "Environments", "Mounts"}
_VALID_SECTIONS = _DOCKER_SECTIONS | {"Params"}


def _find_dockerfile_json(
    files: list,
) -> object | None:
    for f in files:
        if f.path == "Dockerfile.json":
            return f
    return None


def _validate_structure(data: dict) -> None:
    if not isinstance(data.get("docker"), dict):
        raise api_error(400, "validation_error", "Body must have a 'docker' key of type object")
    if not isinstance(data.get("Params"), dict):
        raise api_error(400, "validation_error", "Body must have a 'Params' key of type object")


def _serialize(data: dict) -> str:
    return json.dumps(data, indent=2) + "\n"


@router.get("")
async def get_params(
    dockerfile_id: str,
    _key: dict = require_api_key("dockerfiles.params:read"),
) -> dict:
    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    file = _find_dockerfile_json(files)
    if file is None:
        raise api_error(404, "not_found", "Dockerfile.json not found")
    return json.loads(file.content)


@router.put("")
async def put_params(
    dockerfile_id: str,
    body: dict,
    _key: dict = require_api_key("dockerfiles.params:write"),
) -> dict:
    _validate_structure(body)
    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    file = _find_dockerfile_json(files)
    if file is None:
        raise api_error(404, "not_found", "Dockerfile.json not found")
    updated = await dockerfile_files_service.update(file.id, content=_serialize(body))
    return json.loads(updated.content)


@router.patch("/{section}")
async def patch_params(
    dockerfile_id: str,
    section: str,
    body: Any,
    _key: dict = require_api_key("dockerfiles.params:write"),
) -> dict:
    if section not in _VALID_SECTIONS:
        sections_list = ", ".join(sorted(_VALID_SECTIONS))
        raise api_error(400, "invalid_section", f"Section must be one of: {sections_list}")

    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    file = _find_dockerfile_json(files)
    if file is None:
        raise api_error(404, "not_found", "Dockerfile.json not found")

    current: dict = json.loads(file.content)

    if section == "Params":
        if not isinstance(body, dict):
            raise api_error(400, "validation_error", "Body for 'Params' section must be an object")
        current["Params"] = {**current.get("Params", {}), **body}
    elif section == "Mounts":
        # Mounts is a list — body must be a list; replace entirely
        if not isinstance(body, list):
            raise api_error(400, "validation_error", "Body for 'Mounts' section must be an array")
        current.setdefault("docker", {})["Mounts"] = body
    else:
        if not isinstance(body, dict):
            raise api_error(
                400, "validation_error", f"Body for '{section}' section must be an object"
            )
        docker = current.setdefault("docker", {})
        docker[section] = {**docker.get(section, {}), **body}

    _validate_structure(current)
    updated = await dockerfile_files_service.update(file.id, content=_serialize(current))
    return json.loads(updated.content)
