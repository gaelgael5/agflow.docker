from __future__ import annotations

import contextlib
import secrets
from collections.abc import AsyncIterator
from typing import Any

import aiodocker
import structlog

from agflow.container.adapters.base import AbstractContainerAdapter
from agflow.schemas.containers import ContainerInfo
from agflow.services.container_runner import (
    _AGFLOW_DOCKERFILE_LABEL,
    _AGFLOW_INSTANCE_LABEL,
    _AGFLOW_MANAGED_LABEL,
    MAX_RUNNING_CONTAINERS,
    ContainerNotFoundError,
    ContainerRunnerError,
    ImageNotBuiltError,
    TooManyContainersError,
    _ensure_mount_paths_from_config,
    _generate_tmp_files,
    _load_platform_secrets,
    _parse_docker_ts,
    build_run_config,
    build_service_spec,
    run_task_swarm,
)

_log = structlog.get_logger(__name__)


class DockerSwarmAdapter(AbstractContainerAdapter):
    async def list_running(self) -> list[ContainerInfo]:
        docker = aiodocker.Docker()
        try:
            services = await docker.services.list(
                filters={"label": [f"{_AGFLOW_MANAGED_LABEL}=true"]},
            )
            result: list[ContainerInfo] = []
            for svc in services or []:
                svc_name = (svc.get("Spec") or {}).get("Name", "")
                if not svc_name:
                    continue
                try:
                    tasks = await docker.tasks.list(filters={"service": svc_name})
                except aiodocker.exceptions.DockerError:
                    continue
                container_id = ""
                for task in tasks or []:
                    if (task.get("Status") or {}).get("State") == "running":
                        cs = (task.get("Status") or {}).get("ContainerStatus", {}) or {}
                        cid = cs.get("ContainerID")
                        if cid:
                            container_id = cid
                            break
                if not container_id:
                    continue
                try:
                    container = docker.containers.container(container_id=container_id)
                    inspect = await container.show()
                except aiodocker.exceptions.DockerError:
                    continue
                cfg = inspect.get("Config") or {}
                state = inspect.get("State") or {}
                labels = cfg.get("Labels") or {}
                result.append(ContainerInfo(
                    id=inspect.get("Id", container_id),
                    name=(inspect.get("Name") or svc_name).lstrip("/"),
                    dockerfile_id=labels.get(_AGFLOW_DOCKERFILE_LABEL, ""),
                    image=cfg.get("Image", ""),
                    status=state.get("Status", "running"),
                    created_at=_parse_docker_ts(inspect.get("Created", "")),
                    instance_id=labels.get(_AGFLOW_INSTANCE_LABEL, ""),
                ))
            return result
        finally:
            await docker.close()

    async def launch(
        self,
        dockerfile_id: str,
        *,
        params_json_content: str,
        content_hash: str,
        user_secrets: dict[str, str] | None = None,
    ) -> ContainerInfo:
        import asyncio as _asyncio

        existing = await self.list_running()
        alive = [c for c in existing if c.status in ("running", "created", "restarting")]
        if len(alive) >= MAX_RUNNING_CONTAINERS:
            raise TooManyContainersError(
                f"Maximum de {MAX_RUNNING_CONTAINERS} conteneurs atteint."
            )

        instance_id = secrets.token_hex(3)
        platform_secrets = await _load_platform_secrets()
        all_secrets = {**platform_secrets, **(user_secrets or {})}
        name, spec = build_service_spec(
            dockerfile_id=dockerfile_id,
            params_json_content=params_json_content,
            content_hash=content_hash,
            instance_id=instance_id,
            extra_env=all_secrets,
        )
        classic_image = spec["TaskTemplate"]["ContainerSpec"]["Image"]

        _ensure_mount_paths_from_config(
            dockerfile_id, params_json_content, instance_id, content_hash
        )
        _, classic_config = build_run_config(
            dockerfile_id=dockerfile_id,
            params_json_content=params_json_content,
            content_hash=content_hash,
            instance_id=instance_id,
            extra_env=all_secrets,
        )
        _generate_tmp_files(dockerfile_id, name, classic_config)

        docker = aiodocker.Docker()
        try:
            try:
                await docker.images.inspect(classic_image)
            except aiodocker.exceptions.DockerError as exc:
                if exc.status == 404:
                    raise ImageNotBuiltError(
                        f"Image '{classic_image}' introuvable — compilez le dockerfile d'abord."
                    ) from exc
                raise

            service_create_resp = await docker.services.create(spec)
            service_id = service_create_resp.get("ID") or service_create_resp.get("Id", "")

            container_id = ""
            for _attempt in range(30):
                tasks = await docker.tasks.list(filters={"service": name})
                for task in tasks:
                    state = task.get("Status", {}).get("State", "")
                    if state == "running":
                        cs = task.get("Status", {}).get("ContainerStatus", {}) or {}
                        container_id = cs.get("ContainerID", "")
                        if container_id:
                            break
                if container_id:
                    break
                await _asyncio.sleep(1)

            if not container_id:
                with contextlib.suppress(Exception):
                    await docker.services.delete(service_id)
                raise ContainerRunnerError(
                    f"Service '{name}' créé mais aucun conteneur en cours après 30s"
                )

            container = docker.containers.container(container_id=container_id)
            inspect = await container.show()
            cfg = inspect.get("Config") or {}
            state_info = inspect.get("State") or {}
            labels = cfg.get("Labels") or {}
            info = ContainerInfo(
                id=inspect.get("Id", container_id),
                name=(inspect.get("Name") or name).lstrip("/"),
                dockerfile_id=labels.get(_AGFLOW_DOCKERFILE_LABEL, dockerfile_id),
                image=cfg.get("Image", classic_image),
                status=state_info.get("Status", "running"),
                created_at=_parse_docker_ts(inspect.get("Created", "")),
                instance_id=labels.get(_AGFLOW_INSTANCE_LABEL, instance_id),
            )
            _log.info(
                "container.launch_swarm",
                dockerfile_id=dockerfile_id,
                service_id=service_id,
                service_name=name,
                container_id=info.id,
            )
            return info
        finally:
            await docker.close()

    async def stop(self, container_id: str) -> None:
        docker = aiodocker.Docker()
        try:
            try:
                services = await docker.services.list(
                    filters={"name": [container_id]},
                )
            except aiodocker.exceptions.DockerError:
                services = []

            for svc in services or []:
                svc_id = svc.get("ID") or svc.get("Id", "")
                svc_labels = (svc.get("Spec") or {}).get("Labels", {}) or {}
                svc_name = (svc.get("Spec") or {}).get("Name", "")
                if (
                    svc_labels.get(_AGFLOW_MANAGED_LABEL) == "true"
                    and (svc_name == container_id or svc_id == container_id)
                ):
                    try:
                        await docker.services.delete(svc_id)
                    except aiodocker.exceptions.DockerError as exc:
                        if exc.status not in (404, 409):
                            raise
                    _log.info("container.stop_swarm", service_id=svc_id, service_name=svc_name)
                    return

            try:
                container = docker.containers.container(container_id=container_id)
                inspect = await container.show()
            except aiodocker.exceptions.DockerError as exc:
                if exc.status == 404:
                    raise ContainerNotFoundError(
                        f"Service ou conteneur '{container_id}' introuvable"
                    ) from exc
                raise

            labels = (inspect.get("Config") or {}).get("Labels") or {}
            if labels.get(_AGFLOW_MANAGED_LABEL) != "true":
                raise ContainerNotFoundError(
                    f"Le conteneur '{container_id}' n'est pas géré par agflow"
                )
            with contextlib.suppress(aiodocker.exceptions.DockerError):
                await container.stop(timeout=10)
            try:
                await container.delete(force=True)
            except aiodocker.exceptions.DockerError as exc:
                if exc.status not in (404, 409):
                    raise
            _log.info("container.stop_legacy", container_id=container_id)
        finally:
            await docker.close()

    async def logs(self, container_id: str, *, tail: int = 200) -> list[str]:
        docker = aiodocker.Docker()
        try:
            container = await docker.containers.get(container_id)
            return await container.log(stdout=True, stderr=True, tail=tail)
        finally:
            await docker.close()

    def run_task(  # type: ignore[override]
        self,
        dockerfile_id: str,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        return run_task_swarm(dockerfile_id, **kwargs)
