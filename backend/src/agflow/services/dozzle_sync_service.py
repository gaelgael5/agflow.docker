"""Sync the central Dozzle's ``DOZZLE_REMOTE_AGENT`` list with the machines DB.

Writes ``<AGFLOW_DATA_DIR>/dozzle-agents.env`` with a single line
``DOZZLE_REMOTE_AGENT=host1:7007,host2:7007,…`` then restarts the
``agflow-dozzle`` container via the Docker API so it picks up the new value.

Called on startup and on machine CRUD operations.
"""
from __future__ import annotations

import os
from typing import Any

import structlog

from agflow.services import infra_machines_service

_log = structlog.get_logger(__name__)

_AGENT_FILENAME = "dozzle-agents.env"
_DOZZLE_CONTAINER = "agflow-dozzle"
_DOZZLE_AGENT_PORT = 7007


def _env_file_path() -> str:
    data_dir = os.environ.get("AGFLOW_DATA_DIR", "/app/data")
    return os.path.join(data_dir, _AGENT_FILENAME)


async def _compute_agents_line() -> str:
    machines = await infra_machines_service.list_all()
    central_self = os.environ.get("DOZZLE_CENTRAL_SELF_HOST", "").strip()
    agents: list[str] = []
    seen: set[str] = set()
    for m in machines:
        host = (m.host or "").strip()
        if not host or host in seen:
            continue
        if central_self and host == central_self:
            continue
        seen.add(host)
        agents.append(f"{host}:{_DOZZLE_AGENT_PORT}")
    return ",".join(agents)


def _write_env_file(line: str) -> None:
    path = _env_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"DOZZLE_REMOTE_AGENT={line}\n")


async def _restart_central_container() -> None:
    """Restart the agflow-dozzle container so it picks up the new env value."""
    try:
        import aiodocker
    except ImportError:
        _log.warning("dozzle_sync.aiodocker_missing")
        return
    client = aiodocker.Docker()
    try:
        containers = await client.containers.list(all=True)
        for c in containers:
            name = c._container.get("Names", [""])[0].lstrip("/") if hasattr(c, "_container") else ""
            if name == _DOZZLE_CONTAINER:
                await c.restart(timeout=10)
                _log.info("dozzle_sync.restarted", container=name)
                break
        else:
            _log.info("dozzle_sync.container_not_found", expected=_DOZZLE_CONTAINER)
    except Exception as exc:
        _log.warning("dozzle_sync.restart_failed", error=str(exc))
    finally:
        await client.close()


async def sync(restart: bool = True) -> dict[str, Any]:
    """Recompute the agent list, write the env file, optionally restart dozzle.

    Returns a summary dict with the written line + agent count.
    """
    line = await _compute_agents_line()
    _write_env_file(line)
    count = len([a for a in line.split(",") if a])
    _log.info("dozzle_sync.wrote", count=count)
    if restart and count >= 0:
        await _restart_central_container()
    return {
        "agents_line": line,
        "count": count,
        "file": _env_file_path(),
    }
