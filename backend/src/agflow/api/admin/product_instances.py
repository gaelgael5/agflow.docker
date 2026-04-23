from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

import json

from agflow.auth.dependencies import require_operator as require_admin
from agflow.db.pool import fetch_one as _fetch_one
from agflow.schemas.products import InstanceCreate, InstanceSummary, InstanceUpdate
from agflow.services import (
    infra_certificates_service,
    infra_machines_service,
    product_instances_service,
    ssh_executor,
)

router = APIRouter(
    prefix="/api/admin/product-instances",
    tags=["admin-instances"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[InstanceSummary])
async def list_instances(group_id: UUID | None = None, project_id: UUID | None = None):
    if group_id:
        return await product_instances_service.list_by_group(group_id)
    if project_id:
        return await product_instances_service.list_by_project(project_id)
    return await product_instances_service.list_all()


@router.post("", response_model=InstanceSummary, status_code=status.HTTP_201_CREATED)
async def create_instance(payload: InstanceCreate):
    return await product_instances_service.create(
        group_id=payload.group_id,
        instance_name=payload.instance_name,
        catalog_id=payload.catalog_id,
        variables=payload.variables,
        variable_statuses=payload.variable_statuses,
    )


@router.get("/{instance_id}", response_model=InstanceSummary)
async def get_instance(instance_id: UUID):
    try:
        return await product_instances_service.get_by_id(instance_id)
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{instance_id}", response_model=InstanceSummary)
async def update_instance(instance_id: UUID, payload: InstanceUpdate):
    try:
        return await product_instances_service.update(instance_id, **payload.model_dump(exclude_unset=True))
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instance(instance_id: UUID):
    try:
        await product_instances_service.delete(instance_id)
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


class ActivateRequest(BaseModel):
    service_url: str


@router.post("/{instance_id}/activate")
async def activate_instance(instance_id: UUID, payload: ActivateRequest):
    try:
        instance = await product_instances_service.update_status(instance_id, "active", payload.service_url)
        return {"instance": instance}
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{instance_id}/stop", response_model=InstanceSummary)
async def stop_instance(instance_id: UUID):
    try:
        return await product_instances_service.update_status(instance_id, "stopped")
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Runtime : status / docker start / docker stop / view compose ─

async def _resolve_instance_machine(instance_id: UUID):
    """Find the machine where the instance was most recently deployed."""
    row = await _fetch_one(
        """
        SELECT machine_id
        FROM deployment_instances
        WHERE instance_id = $1 AND machine_id IS NOT NULL
        ORDER BY deployed_at DESC
        LIMIT 1
        """,
        instance_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instance not deployed yet — no machine recorded",
        )
    return row["machine_id"]


async def _ssh_for_machine(machine_id: UUID):
    creds = await infra_machines_service.get_credentials(machine_id)
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
    }


@router.get("/{instance_id}/runtime-status")
async def get_instance_runtime_status(instance_id: UUID):
    """Query docker ps on the instance's target machine, filtered by label."""
    machine_id = await _resolve_instance_machine(instance_id)
    ssh = await _ssh_for_machine(machine_id)
    try:
        result = await ssh_executor.exec_command(
            **ssh,
            command=(
                f"docker ps -a --filter 'label=agflow.instance_id={instance_id}' "
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

    def _normalize_state(state: str) -> str:
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
        states = {_normalize_state(c.get("State", "") or c.get("Status", "")) for c in containers}
        if states == {"running"}:
            overall = "running"
        elif "running" in states:
            overall = "partial"
        elif states == {"stopped"} or states == {"exited"}:
            overall = "stopped"
        else:
            overall = "mixed"

    return {
        "instance_id": str(instance_id),
        "machine_id": str(machine_id),
        "overall_state": overall,
        "containers": containers,
    }


@router.post("/{instance_id}/runtime-start")
async def runtime_start_instance(instance_id: UUID):
    machine_id = await _resolve_instance_machine(instance_id)
    ssh = await _ssh_for_machine(machine_id)
    try:
        result = await ssh_executor.exec_command(
            **ssh,
            command=(
                f"docker ps -a --filter 'label=agflow.instance_id={instance_id}' -q "
                f"| xargs -r docker start"
            ),
        )
    except ssh_executor.SSHConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {
        "instance_id": str(instance_id),
        "exit_code": result.get("exit_code", -1),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
    }


@router.post("/{instance_id}/runtime-stop")
async def runtime_stop_instance(instance_id: UUID):
    machine_id = await _resolve_instance_machine(instance_id)
    ssh = await _ssh_for_machine(machine_id)
    try:
        result = await ssh_executor.exec_command(
            **ssh,
            command=(
                f"docker ps -a --filter 'label=agflow.instance_id={instance_id}' -q "
                f"| xargs -r docker stop"
            ),
        )
    except ssh_executor.SSHConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {
        "instance_id": str(instance_id),
        "exit_code": result.get("exit_code", -1),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
    }


@router.get("/{instance_id}/compose")
async def get_instance_compose(instance_id: UUID):
    """Return the compose snippet (services + their labels) for this instance.

    Parses the latest deployment's generated_compose and extracts the services
    whose container has label agflow.instance_id=<instance_id>.
    """
    import yaml as _yaml

    row = await _fetch_one(
        """
        SELECT di.machine_id, pd.generated_compose, pd.generated_env, pd.id AS deployment_id
        FROM deployment_instances di
        JOIN project_deployments pd ON pd.id = di.deployment_id
        WHERE di.instance_id = $1
        ORDER BY di.deployed_at DESC
        LIMIT 1
        """,
        instance_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instance not deployed yet — no compose recorded",
        )

    full_compose = row.get("generated_compose") or ""
    try:
        parsed = _yaml.safe_load(full_compose) or {}
    except Exception:
        return {
            "deployment_id": str(row["deployment_id"]),
            "machine_id": str(row["machine_id"]) if row.get("machine_id") else None,
            "compose_yaml": full_compose,
            "filtered": False,
        }

    target_label = f"agflow.instance_id={instance_id}"
    services = parsed.get("services") or {}
    filtered_services = {}
    for name, svc in services.items():
        labels = svc.get("labels") or []
        if target_label in labels:
            filtered_services[name] = svc

    subset = {"services": filtered_services}
    if "networks" in parsed:
        subset["networks"] = parsed["networks"]

    return {
        "deployment_id": str(row["deployment_id"]),
        "machine_id": str(row["machine_id"]) if row.get("machine_id") else None,
        "compose_yaml": _yaml.dump(subset, default_flow_style=False, allow_unicode=True, sort_keys=False),
        "filtered": True,
    }
