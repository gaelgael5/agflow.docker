from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agflow.auth.dependencies import require_admin
from agflow.schemas.containers import ContainerInfo
from agflow.services import (
    build_service,
    container_runner,
    dockerfile_files_service,
    dockerfiles_service,
)


class TaskRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=16_000)
    timeout_seconds: int = Field(default=600, ge=1, le=3600)
    model: str = Field(default="", max_length=100)
    secrets: dict[str, str] = Field(default_factory=dict)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-containers"],
    dependencies=[Depends(require_admin)],
)


@router.post(
    "/dockerfiles/{dockerfile_id}/run",
    response_model=ContainerInfo,
    status_code=status.HTTP_201_CREATED,
)
class RunPayload(BaseModel):
    secrets: dict[str, str] = Field(default_factory=dict)


async def run_dockerfile(
    dockerfile_id: str, payload: RunPayload | None = None
) -> ContainerInfo:
    """Launch a container from a previously-built image of the dockerfile.

    Reads Dockerfile.json for the runtime config, resolves all {KEY} templates,
    and creates + starts the container via aiodocker.
    """
    try:
        dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    # Only runnable if the current content has a successful build.
    if dockerfile.display_status != "up_to_date":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Le dockerfile n'est pas à jour — compile-le d'abord pour "
                "pouvoir lancer une instance."
            ),
        )

    # Fetch Dockerfile.json content.
    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    params_file = next((f for f in files if f.path == "Dockerfile.json"), None)
    if params_file is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dockerfile.json manquant — ce dockerfile ne peut pas être lancé.",
        )

    tag = build_service.image_tag_for(dockerfile_id, dockerfile.current_hash)
    # Sanity: image tag must match what's in the config after resolution.
    _ = tag  # placeholder; config.Image already resolves to the same value

    try:
        return await container_runner.start(
            dockerfile_id,
            params_json_content=params_file.content,
            content_hash=dockerfile.current_hash,
            user_secrets=(payload.secrets if payload else None) or None,
        )
    except container_runner.ImageNotBuiltError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except container_runner.TooManyContainersError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
    except container_runner.InvalidParamsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("/containers", response_model=list[ContainerInfo])
async def list_containers() -> list[ContainerInfo]:
    """List all agflow-managed containers (running, stopped, etc.)."""
    return await container_runner.list_running()


@router.delete(
    "/containers/{container_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def stop_container(container_id: str) -> None:
    try:
        await container_runner.stop(container_id)
    except container_runner.ContainerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/dockerfiles/{dockerfile_id}/task")
async def run_task(
    dockerfile_id: str, payload: TaskRequest
) -> StreamingResponse:
    """One-shot chat task.

    Starts a container, feeds a JSON task on stdin, streams newline-delimited
    JSON events back to the client as they are emitted by the agent. Final
    event is ``{"type": "done", "status": ..., "exit_code": ...}``. Container
    is removed on exit.
    """
    try:
        dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    if dockerfile.display_status != "up_to_date":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Le dockerfile n'est pas à jour — compile-le avant de "
                "dialoguer avec lui."
            ),
        )

    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    params_file = next((f for f in files if f.path == "Dockerfile.json"), None)
    if params_file is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dockerfile.json manquant.",
        )

    task_payload = {
        "task_id": str(uuid.uuid4()),
        "payload": {"instruction": payload.instruction},
        "timeout_seconds": payload.timeout_seconds,
        "model": payload.model or None,
    }

    async def _stream():
        try:
            async for event in container_runner.run_task(
                dockerfile_id,
                params_json_content=params_file.content,
                content_hash=dockerfile.current_hash,
                task_payload=task_payload,
                timeout_seconds=payload.timeout_seconds,
                user_secrets=payload.secrets,
            ):
                yield (json.dumps(event) + "\n").encode("utf-8")
        except container_runner.ImageNotBuiltError as exc:
            yield (
                json.dumps({"type": "error", "message": str(exc)}) + "\n"
            ).encode("utf-8")
        except container_runner.TooManyContainersError as exc:
            yield (
                json.dumps({"type": "error", "message": str(exc)}) + "\n"
            ).encode("utf-8")
        except container_runner.InvalidParamsError as exc:
            yield (
                json.dumps({"type": "error", "message": str(exc)}) + "\n"
            ).encode("utf-8")
        except Exception as exc:  # pragma: no cover — surface unexpected
            yield (
                json.dumps({"type": "error", "message": str(exc)}) + "\n"
            ).encode("utf-8")

    return StreamingResponse(_stream(), media_type="application/x-ndjson")
