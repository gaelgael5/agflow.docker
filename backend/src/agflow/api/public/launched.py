from __future__ import annotations

import contextlib
import json
from uuid import UUID

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agflow.api.public.errors import api_error
from agflow.auth.api_key import require_api_key
from agflow.schemas.launched import LaunchedTaskSummary
from agflow.services import (
    container_runner,
    dockerfile_files_service,
    dockerfiles_service,
    launched_service,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["public-launched"],
)


class TaskRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=16_000)
    timeout_seconds: int = Field(default=600, ge=1, le=3600)
    model: str = Field(default="", max_length=100)
    secrets: dict[str, str] = Field(default_factory=dict)


@router.post("/dockerfiles/{dockerfile_id}/task")
async def run_task(
    dockerfile_id: str,
    payload: TaskRequest,
    _key: dict = require_api_key("containers.chat:write"),  # noqa: B008
) -> StreamingResponse:
    """Launch a one-shot task and stream events back.

    Returns an agflow task UUID in the first event, NOT the Docker container ID.
    """
    try:
        dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise api_error(404, "not_found", str(exc)) from exc

    if dockerfile.display_status != "up_to_date":
        raise api_error(
            409,
            "not_up_to_date",
            "Compile le dockerfile avant de lancer une tâche.",
        )

    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    params_file = next((f for f in files if f.path == "Dockerfile.json"), None)
    if params_file is None:
        raise api_error(409, "missing_params", "Dockerfile.json manquant.")

    # Create the launched task record BEFORE starting the container.
    task_record = await launched_service.create(
        dockerfile_id=dockerfile_id,
        instruction=payload.instruction,
    )

    task_payload = {
        "task_id": str(task_record.id),
        "payload": {"instruction": payload.instruction},
        "timeout_seconds": payload.timeout_seconds,
        "model": payload.model or None,
    }

    async def _stream():
        # First event: the agflow task UUID (NOT the Docker container ID).
        yield (
            json.dumps(
                {
                    "type": "started",
                    "task_id": str(task_record.id),
                    "dockerfile_id": dockerfile_id,
                }
            )
            + "\n"
        ).encode("utf-8")

        final_status = "error"
        final_exit_code = None
        try:
            async for event in container_runner.run_task(
                dockerfile_id,
                params_json_content=params_file.content,
                content_hash=dockerfile.current_hash,
                task_payload=task_payload,
                timeout_seconds=payload.timeout_seconds,
                user_secrets=payload.secrets or None,
                on_container_started=lambda cid, cname: _record_container(
                    task_record.id, cid, cname
                ),
            ):
                yield (json.dumps(event) + "\n").encode("utf-8")
                if event.get("type") == "done":
                    final_status = event.get("status", "error")
                    final_exit_code = event.get("exit_code")
        except container_runner.ImageNotBuiltError as exc:
            yield (
                json.dumps({"type": "error", "message": str(exc)}) + "\n"
            ).encode("utf-8")
            final_status = "error"
        except container_runner.TooManyContainersError as exc:
            yield (
                json.dumps({"type": "error", "message": str(exc)}) + "\n"
            ).encode("utf-8")
            final_status = "error"
        except container_runner.InvalidParamsError as exc:
            yield (
                json.dumps({"type": "error", "message": str(exc)}) + "\n"
            ).encode("utf-8")
            final_status = "error"
        except Exception as exc:
            yield (
                json.dumps({"type": "error", "message": str(exc)}) + "\n"
            ).encode("utf-8")
            final_status = "error"
        finally:
            await launched_service.set_finished(
                task_record.id, final_status, final_exit_code
            )

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


async def _record_container(task_id: UUID, container_id: str, container_name: str):
    """Callback invoked by run_task once the Docker container is created."""
    await launched_service.set_running(task_id, container_id, container_name)


@router.get("/launched", response_model=list[LaunchedTaskSummary])
async def list_launched(
    dockerfile_id: str | None = None,
    _key: dict = require_api_key("containers.chat:read"),  # noqa: B008
) -> list[LaunchedTaskSummary]:
    return await launched_service.list_all(dockerfile_id)


@router.delete("/launched/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def stop_launched(
    task_id: UUID,
    _key: dict = require_api_key("containers:stop"),  # noqa: B008
) -> None:
    try:
        row = await launched_service.get_by_id(task_id)
    except launched_service.TaskNotFoundError as exc:
        raise api_error(404, "not_found", str(exc)) from exc

    container_id = row.get("container_id")
    if container_id and row["status"] in ("pending", "running"):
        with contextlib.suppress(container_runner.ContainerNotFoundError):
            await container_runner.stop(container_id)

    await launched_service.stop(task_id)
