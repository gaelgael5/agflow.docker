from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agflow.auth.dependencies import require_admin
from agflow.schemas.containers import ContainerInfo
from agflow.services import (
    agent_files_service,
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


class RunPayload(BaseModel):
    secrets: dict[str, str] = Field(default_factory=dict)


@router.post(
    "/dockerfiles/{dockerfile_id}/run",
    response_model=ContainerInfo,
    status_code=status.HTTP_201_CREATED,
)
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


@router.post(
    "/dockerfiles/{dockerfile_id}/regenerate-tmp",
    status_code=status.HTTP_200_OK,
)
async def regenerate_tmp_files(
    dockerfile_id: str, payload: RunPayload | None = None
) -> dict[str, str]:
    """Regenerate .tmp/run.sh and .tmp/.env without starting a container."""
    try:
        dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    params_file = next((f for f in files if f.path == "Dockerfile.json"), None)
    if params_file is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dockerfile.json manquant.",
        )

    # Load platform secrets + user vault secrets, same as container start.
    platform_secrets = await container_runner._load_platform_secrets()
    user_secrets = (payload.secrets if payload else None) or {}
    all_secrets = {**platform_secrets, **user_secrets}

    try:
        name, config = container_runner.build_run_config(
            dockerfile_id=dockerfile_id,
            params_json_content=params_file.content,
            content_hash=dockerfile.current_hash,
            instance_id="preview",
            extra_env=all_secrets,
        )
    except container_runner.InvalidParamsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    container_runner._generate_tmp_files(dockerfile_id, name, config)
    return {"status": "ok"}


@router.get("/containers", response_model=list[ContainerInfo])
async def list_containers() -> list[ContainerInfo]:
    """List all agflow-managed containers (running, stopped, etc.)."""
    return await container_runner.list_running()


@router.get("/containers/{container_id}/logs")
async def container_logs(container_id: str, tail: int = 200) -> str:
    import aiodocker

    docker = aiodocker.Docker()
    try:
        container = await docker.containers.get(container_id)
        lines = await container.log(stdout=True, stderr=True, tail=tail)
        return "".join(lines)
    except aiodocker.exceptions.DockerError as exc:
        if exc.status == 404:
            raise HTTPException(status_code=404, detail="Container not found") from exc
        raise
    finally:
        await docker.close()


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
                cleanup=True,
                session_id=task_payload["task_id"],
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


@router.post("/agents/{agent_slug}/task")
async def run_agent_task(
    agent_slug: str,
    payload: TaskRequest,
    request: Request,
    user_email: str = Depends(require_admin),
) -> StreamingResponse:
    """One-shot agent task using the agent's generated config.

    Loads the agent's prompt.md, prepends it to the instruction, and runs
    the container with the agent's Dockerfile.json overrides (env, mounts
    including MCP config). Injects session identity as env vars.
    """
    import os

    # Extract the raw token so the agent can call back APIs
    auth_header = request.headers.get("authorization", "")
    raw_token = auth_header.removeprefix("Bearer ").strip() if auth_header else ""

    data_dir = os.environ.get("AGFLOW_DATA_DIR", "/app/data")
    agent_data = agent_files_service.read_agent(agent_slug)
    if not agent_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_slug}' not found",
        )

    dockerfile_id = agent_data.get("dockerfile_id", "")
    if not dockerfile_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent has no dockerfile_id configured",
        )

    try:
        dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    if dockerfile.display_status != "up_to_date":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Le dockerfile n'est pas à jour — compilez-le d'abord.",
        )

    # Read generated prompt
    prompt_path = os.path.join(
        data_dir, "agents", agent_slug, "generated", "prompt.md"
    )
    prompt = ""
    if os.path.isfile(prompt_path):
        with open(prompt_path, encoding="utf-8") as f:
            prompt = f.read()

    # Read generated .env for agent secrets
    env_path = os.path.join(
        data_dir, "agents", agent_slug, "generated", ".env"
    )
    agent_secrets: dict[str, str] = {}
    if os.path.isfile(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    agent_secrets[k.strip()] = v.strip()

    # Merge: agent secrets + user-provided secrets (user overrides agent)
    merged_secrets = {**agent_secrets, **payload.secrets}

    # Build instruction with prompt prefix
    full_instruction = payload.instruction
    if prompt:
        full_instruction = (
            f"<system>\n{prompt}\n</system>\n\n{payload.instruction}"
        )

    # Load Dockerfile.json with agent overrides applied
    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    params_file = next((f for f in files if f.path == "Dockerfile.json"), None)
    if params_file is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dockerfile.json manquant.",
        )

    # Apply agent env/mount overrides to Dockerfile.json
    params_json = json.loads(params_file.content)
    docker_block = params_json.get("docker", {})

    # Merge agent env overrides
    env_overrides = agent_data.get("env_overrides", {})
    if env_overrides:
        envs = docker_block.get("Environments", {})
        for key, override in env_overrides.items():
            if isinstance(override, dict) and not override.get("excluded"):
                envs[key] = override.get("value", envs.get(key, ""))
            elif isinstance(override, dict) and override.get("excluded"):
                envs.pop(key, None)
        docker_block["Environments"] = envs

    # Merge agent mount overrides
    mount_overrides = agent_data.get("mount_overrides", {})
    if mount_overrides:
        mounts = docker_block.get("Mounts", [])
        mounts = [
            m for m in mounts
            if not (isinstance(mount_overrides.get(m.get("target")), dict)
                    and mount_overrides[m["target"]].get("excluded"))
        ]
        docker_block["Mounts"] = mounts

    # Inject session identity env vars so the agent knows who it is
    session_id = str(uuid.uuid4())
    envs = docker_block.get("Environments", {})
    envs["AGFLOW_SESSION_ID"] = session_id
    envs["AGFLOW_USER_EMAIL"] = user_email
    envs["AGFLOW_TOKEN"] = raw_token
    envs["AGFLOW_API_URL"] = "http://agflow-backend:8000"
    docker_block["Environments"] = envs

    params_json["docker"] = docker_block
    resolved_params_content = json.dumps(params_json, ensure_ascii=False, indent=2)

    task_payload = {
        "task_id": str(uuid.uuid4()),
        "payload": {"instruction": full_instruction},
        "timeout_seconds": payload.timeout_seconds,
        "model": payload.model or None,
    }

    async def _stream():
        try:
            async for event in container_runner.run_task(
                dockerfile_id,
                params_json_content=resolved_params_content,
                content_hash=dockerfile.current_hash,
                task_payload=task_payload,
                timeout_seconds=payload.timeout_seconds,
                user_secrets=merged_secrets,
                cleanup=True,
                session_id=task_payload["task_id"],
            ):
                yield (json.dumps(event) + "\n").encode("utf-8")
        except Exception as exc:
            yield (
                json.dumps({"type": "error", "message": str(exc)}) + "\n"
            ).encode("utf-8")

    return StreamingResponse(_stream(), media_type="application/x-ndjson")
