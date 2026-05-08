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
    ImageNotBuiltError,
    TooManyContainersError,
    _ensure_mount_paths_from_config,
    _generate_tmp_files,
    _load_platform_secrets,
    _parse_docker_ts,
    build_run_config,
    run_task,
)

_log = structlog.get_logger(__name__)


def _info_from_inspect(inspect: dict[str, Any]) -> ContainerInfo:
    cfg = inspect.get("Config") or {}
    state = inspect.get("State") or {}
    labels = cfg.get("Labels") or {}
    name = (inspect.get("Name") or "").lstrip("/")
    return ContainerInfo(
        id=inspect.get("Id", ""),
        name=name,
        dockerfile_id=labels.get(_AGFLOW_DOCKERFILE_LABEL, ""),
        image=cfg.get("Image", ""),
        status=state.get("Status", "running"),
        created_at=_parse_docker_ts(inspect.get("Created", "")),
        instance_id=labels.get(_AGFLOW_INSTANCE_LABEL, ""),
    )


class DockerStandaloneAdapter(AbstractContainerAdapter):
    async def list_running(self) -> list[ContainerInfo]:
        docker = aiodocker.Docker()
        try:
            containers = await docker.containers.list(
                filters={"label": [f"{_AGFLOW_MANAGED_LABEL}=true"]}
            )
            result: list[ContainerInfo] = []
            for c in containers or []:
                try:
                    inspect = await c.show()
                    result.append(_info_from_inspect(inspect))
                except aiodocker.exceptions.DockerError:
                    continue
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
        existing = await self.list_running()
        alive = [c for c in existing if c.status in ("running", "created", "restarting")]
        if len(alive) >= MAX_RUNNING_CONTAINERS:
            raise TooManyContainersError(
                f"Maximum de {MAX_RUNNING_CONTAINERS} conteneurs atteint."
            )

        instance_id = secrets.token_hex(3)
        platform_secrets = await _load_platform_secrets()
        all_secrets = {**platform_secrets, **(user_secrets or {})}
        name, config = build_run_config(
            dockerfile_id=dockerfile_id,
            params_json_content=params_json_content,
            content_hash=content_hash,
            instance_id=instance_id,
            extra_env=all_secrets,
        )
        # Interactive launch: keep stdin open so the entrypoint doesn't receive
        # EOF immediately and exit. Tty gives a proper terminal for docker exec.
        config["Tty"] = True
        config["OpenStdin"] = True
        config["StdinOnce"] = False
        _ensure_mount_paths_from_config(
            dockerfile_id, params_json_content, instance_id, content_hash
        )
        _generate_tmp_files(dockerfile_id, name, config)

        docker = aiodocker.Docker()
        try:
            try:
                await docker.images.inspect(config["Image"])
            except aiodocker.exceptions.DockerError as exc:
                if exc.status == 404:
                    raise ImageNotBuiltError(
                        f"Image '{config['Image']}' introuvable — compilez le dockerfile d'abord."
                    ) from exc
                raise

            container = await docker.containers.create(config=config, name=name)
            await container.start()
            inspect = await container.show()
            info = _info_from_inspect(inspect)
            _log.info(
                "container.launch_standalone",
                dockerfile_id=dockerfile_id,
                container_id=info.id,
                name=name,
            )
            return info
        finally:
            await docker.close()

    async def stop(self, container_id: str) -> None:
        docker = aiodocker.Docker()
        try:
            try:
                container = docker.containers.container(container_id=container_id)
                inspect = await container.show()
            except aiodocker.exceptions.DockerError as exc:
                if exc.status == 404:
                    raise ContainerNotFoundError(
                        f"Conteneur '{container_id}' introuvable"
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
            _log.info("container.stop_standalone", container_id=container_id)
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
        return run_task(dockerfile_id, **kwargs)
