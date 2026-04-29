from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.runtimes import (
    ProjectGroupRuntimeDetail,
    ProjectGroupRuntimeRow,
    ProjectRuntimeRow,
)
from agflow.services import (
    infra_certificates_service,
    infra_machines_service,
    project_runtimes_service,
    ssh_executor,
)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-runtimes"],
    dependencies=[Depends(require_admin)],
)


@router.get("/groups/{group_id}/runtimes", response_model=list[ProjectGroupRuntimeRow])
async def list_group_runtimes(group_id: UUID):
    return await project_runtimes_service.list_group_runtimes_by_group(group_id)


@router.get("/projects/{project_id}/runtimes", response_model=list[ProjectRuntimeRow])
async def list_project_runtimes(project_id: UUID):
    return await project_runtimes_service.list_runtimes_by_project(project_id)


@router.get("/group-runtimes/{runtime_id}", response_model=ProjectGroupRuntimeDetail)
async def get_group_runtime(runtime_id: UUID):
    try:
        return await project_runtimes_service.get_group_runtime(runtime_id)
    except project_runtimes_service.ProjectGroupRuntimeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Runtime runtime controls (status / start / stop) ─────


async def _ssh_for_runtime(runtime_id: UUID) -> tuple[dict, UUID]:
    detail = await project_runtimes_service.get_group_runtime(runtime_id)
    if not detail.machine_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Runtime has no machine assigned",
        )
    creds = await infra_machines_service.get_credentials(detail.machine_id)
    private_key = None
    passphrase = None
    if creds.get("certificate_id"):
        cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
        private_key = cert.get("private_key")
        passphrase = cert.get("passphrase")
    return {
        "host": creds["host"], "port": creds["port"],
        "username": creds["username"], "password": creds["password"],
        "private_key": private_key, "passphrase": passphrase,
    }, detail.machine_id


@router.get("/group-runtimes/{runtime_id}/status")
async def runtime_status(runtime_id: UUID):
    ssh, machine_id = await _ssh_for_runtime(runtime_id)
    try:
        result = await ssh_executor.exec_command(
            **ssh,
            command=(
                f"docker ps -a --filter 'label=agflow.runtime_id={runtime_id}' "
                f"--format '{{{{json .}}}}'"
            ),
        )
    except ssh_executor.SSHConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    containers = []
    for line in (result.get("stdout") or "").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            containers.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    def _normalize(state: str) -> str:
        low = (state or "").lower()
        if "up" in low:
            return "running"
        if "exited" in low or "stopped" in low:
            return "stopped"
        if "created" in low:
            return "created"
        return low or "unknown"

    overall = "unknown"
    if containers:
        states = {_normalize(c.get("State", "") or c.get("Status", "")) for c in containers}
        if states == {"running"}:
            overall = "running"
        elif "running" in states:
            overall = "partial"
        elif states <= {"stopped", "exited"}:
            overall = "stopped"
        else:
            overall = "mixed"
    return {
        "runtime_id": str(runtime_id),
        "machine_id": str(machine_id),
        "overall_state": overall,
        "containers": containers,
    }


@router.post("/group-runtimes/{runtime_id}/start")
async def runtime_start(runtime_id: UUID):
    ssh, _mid = await _ssh_for_runtime(runtime_id)
    try:
        result = await ssh_executor.exec_command(
            **ssh,
            command=(
                f"docker ps -a --filter 'label=agflow.runtime_id={runtime_id}' -q "
                f"| xargs -r docker start"
            ),
        )
    except ssh_executor.SSHConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"runtime_id": str(runtime_id), **{k: result.get(k, "") for k in ("exit_code", "stdout", "stderr")}}


@router.delete("/group-runtimes/{runtime_id}", status_code=status.HTTP_204_NO_CONTENT)
async def runtime_delete(runtime_id: UUID):
    """Stop containers, remove remote directory, then soft-delete the runtime row.

    Idempotent — missing containers or missing directory don't fail the delete.
    """
    try:
        detail = await project_runtimes_service.get_group_runtime(runtime_id)
    except project_runtimes_service.ProjectGroupRuntimeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if detail.machine_id:
        try:
            ssh, _ = await _ssh_for_runtime(runtime_id)
        except HTTPException:
            ssh = None
        if ssh:
            remote = (detail.remote_path or "").strip()
            # 1. Stop + remove containers owned by this runtime
            try:
                if remote:
                    await ssh_executor.exec_command(
                        **ssh,
                        command=(
                            f"cd {remote} && docker compose down --volumes --remove-orphans "
                            f"2>/dev/null || true"
                        ),
                    )
                await ssh_executor.exec_command(
                    **ssh,
                    command=(
                        f"docker ps -aq --filter 'label=agflow.runtime_id={runtime_id}' "
                        f"| xargs -r docker rm -f"
                    ),
                )
            except Exception:
                pass  # best-effort; still proceed to rm -rf + DB update
            # 2. Remove remote directory
            if remote:
                try:
                    await ssh_executor.exec_command(
                        **ssh, command=f"rm -rf {remote}",
                    )
                except Exception:
                    pass

    await project_runtimes_service.soft_delete_group_runtime(runtime_id)


@router.post("/group-runtimes/{runtime_id}/stop")
async def runtime_stop(runtime_id: UUID):
    ssh, _mid = await _ssh_for_runtime(runtime_id)
    try:
        result = await ssh_executor.exec_command(
            **ssh,
            command=(
                f"docker ps -a --filter 'label=agflow.runtime_id={runtime_id}' -q "
                f"| xargs -r docker stop"
            ),
        )
    except ssh_executor.SSHConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"runtime_id": str(runtime_id), **{k: result.get(k, "") for k in ("exit_code", "stdout", "stderr")}}
