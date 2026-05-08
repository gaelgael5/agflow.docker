from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from agflow.schemas.containers import ContainerInfo


class AbstractContainerAdapter(ABC):
    @abstractmethod
    async def list_running(self) -> list[ContainerInfo]: ...

    @abstractmethod
    async def launch(
        self,
        dockerfile_id: str,
        *,
        params_json_content: str,
        content_hash: str,
        user_secrets: dict[str, str] | None = None,
    ) -> ContainerInfo: ...

    @abstractmethod
    async def stop(self, container_id: str) -> None: ...

    @abstractmethod
    async def logs(self, container_id: str, *, tail: int = 200) -> list[str]: ...

    @abstractmethod
    async def resolve_container_id(self, container_id: str) -> str:
        """Résout un ID opaque (container ID ou service Swarm) vers un container ID réel."""
        ...

    @abstractmethod
    def run_task(
        self,
        dockerfile_id: str,
        *,
        params_json_content: str,
        content_hash: str,
        task_payload: dict[str, Any],
        timeout_seconds: int = 600,
        user_secrets: dict[str, str] | None = None,
        on_container_started: Any | None = None,
        cleanup: bool = False,
        session_id: str | None = None,
        agent_instance_id: str | None = None,
        mount_base_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...


class NoneAdapter(AbstractContainerAdapter):
    """Adapter retourné quand aucun runtime n'est disponible sur la machine."""

    async def list_running(self) -> list[ContainerInfo]:
        return []

    async def launch(
        self,
        dockerfile_id: str,
        *,
        params_json_content: str,
        content_hash: str,
        user_secrets: dict[str, str] | None = None,
    ) -> ContainerInfo:
        from agflow.services.container_runner import ContainerRunnerError
        raise ContainerRunnerError("Aucun runtime container détecté sur cette machine.")

    async def stop(self, container_id: str) -> None:
        from agflow.services.container_runner import ContainerNotFoundError
        raise ContainerNotFoundError(
            f"Aucun runtime container — impossible de stopper '{container_id}'"
        )

    async def logs(self, container_id: str, *, tail: int = 200) -> list[str]:
        return []

    async def resolve_container_id(self, container_id: str) -> str:
        return container_id

    async def run_task(  # type: ignore[override]
        self,
        dockerfile_id: str,
        *,
        params_json_content: str,
        content_hash: str,
        task_payload: dict[str, Any],
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        from agflow.services.container_runner import ContainerRunnerError
        raise ContainerRunnerError("Aucun runtime container détecté sur cette machine.")
        # make type checker happy — never reached
        yield {}  # type: ignore[misc]
