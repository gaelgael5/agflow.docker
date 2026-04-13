from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agflow.auth.api_key import require_api_key
from agflow.schemas.containers import ContainerInfo
from agflow.services import container_runner, dockerfile_files_service, dockerfiles_service

router = APIRouter(prefix="/api/v1", tags=["public-containers"])


class RunPayload(BaseModel):
    secrets: dict[str, str] = Field(default_factory=dict)


@router.get("/containers", response_model=list[ContainerInfo])
async def list_containers(
    _key: dict = require_api_key("containers:read"),
) -> list[ContainerInfo]:
    return await container_runner.list_running()


@router.post("/dockerfiles/{dockerfile_id}/run", response_model=ContainerInfo)
async def run_container(
    dockerfile_id: str,
    payload: RunPayload | None = None,
    _key: dict = require_api_key("containers:run"),
) -> ContainerInfo:
    dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    params_file = next((f for f in files if f.path == "Dockerfile.json"), None)

    return await container_runner.start(
        dockerfile_id,
        params_json_content=params_file.content if params_file else "{}",
        content_hash=dockerfile.current_hash,
        user_secrets=(payload.secrets if payload else None) or None,
    )


@router.post("/containers/{container_id}/stop")
async def stop_container(
    container_id: str,
    _key: dict = require_api_key("containers:stop"),
) -> dict:
    await container_runner.stop(container_id)
    return {"status": "stopped"}
