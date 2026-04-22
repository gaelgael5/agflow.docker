from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.products import DeploymentCreate, DeploymentSummary, DeploymentUpdate
from agflow.services import (
    group_scripts_service,
    infra_certificates_service,
    infra_machines_service,
    project_deployments_service,
    projects_service,
    scripts_service,
    ssh_executor,
    users_service,
)

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/project-deployments",
    tags=["admin-deployments"],
)

_admin = [Depends(require_admin)]


async def _get_user_id(email: str = Depends(require_admin)) -> UUID:
    user = await users_service.get_by_email(email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user.id


@router.get("", response_model=list[DeploymentSummary], dependencies=_admin)
async def list_deployments(project_id: UUID | None = None):
    if project_id:
        return await project_deployments_service.list_by_project(project_id)
    return []


@router.post("", response_model=DeploymentSummary, status_code=status.HTTP_201_CREATED)
async def create_deployment(payload: DeploymentCreate, user_id: UUID = Depends(_get_user_id)):
    return await project_deployments_service.create(
        project_id=payload.project_id,
        user_id=user_id,
        group_servers=payload.group_servers,
    )


@router.get("/{deployment_id}", response_model=DeploymentSummary, dependencies=_admin)
async def get_deployment(deployment_id: UUID):
    try:
        return await project_deployments_service.get_by_id(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{deployment_id}", response_model=DeploymentSummary, dependencies=_admin)
async def update_deployment(deployment_id: UUID, payload: DeploymentUpdate):
    try:
        if payload.group_servers is not None:
            return await project_deployments_service.update_group_servers(
                deployment_id, payload.group_servers,
            )
        return await project_deployments_service.get_by_id(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


class GenerateRequest(BaseModel):
    user_secrets: dict[str, str] = {}


@router.post("/{deployment_id}/generate", response_model=DeploymentSummary, dependencies=_admin)
async def generate_deployment(deployment_id: UUID, payload: GenerateRequest | None = None):
    try:
        return await project_deployments_service.generate(
            deployment_id,
            user_secrets=payload.user_secrets if payload else None,
        )
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


async def _ssh_kwargs_for_machine(machine_id: UUID) -> dict[str, Any]:
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


def _parse_last_json(stdout: str) -> dict | None:
    """Find and parse the last JSON line from script stdout."""
    import json as _json
    for line in reversed((stdout or "").splitlines()):
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                return _json.loads(stripped)
            except _json.JSONDecodeError:
                continue
    return None


def _merge_env_with_values(env_text: str, values: dict[str, str]) -> str:
    """For each VAR=... line, if values has VAR, replace the value."""
    out_lines: list[str] = []
    for line in (env_text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out_lines.append(line)
            continue
        name = line.split("=", 1)[0].strip()
        if name in values:
            out_lines.append(f"{name}={values[name]}")
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


async def _run_group_script(link: Any, script_content: str) -> dict[str, Any]:
    """Upload + exec a shell script on its target machine. Returns result dict."""
    import secrets as _secrets
    try:
        ssh = await _ssh_kwargs_for_machine(link.machine_id)
    except Exception as exc:
        return {
            "script": link.script_name, "machine": link.machine_name,
            "timing": link.timing, "success": False, "error": str(exc),
        }

    remote_path = f"/tmp/agflow-script-{_secrets.token_hex(8)}.sh"
    try:
        await ssh_executor.exec_command(**ssh, command=f"cat > {remote_path}", input=script_content)
        await ssh_executor.exec_command(**ssh, command=f"chmod +x {remote_path}")
        result = await ssh_executor.exec_command(**ssh, command=f"bash {remote_path}")
    except Exception as exc:
        return {
            "script": link.script_name, "machine": link.machine_name,
            "timing": link.timing, "success": False, "error": str(exc),
        }
    finally:
        try:
            await ssh_executor.exec_command(**ssh, command=f"rm -f {remote_path}")
        except Exception:
            pass

    exit_code = result.get("exit_code", -1)
    return {
        "script": link.script_name, "machine": link.machine_name,
        "timing": link.timing, "position": link.position,
        "success": exit_code == 0, "exit_code": exit_code,
        "stdout": result.get("stdout", ""), "stderr": result.get("stderr", ""),
    }


def _collect_env_from_script(
    link: Any, parsed_json: dict,
) -> dict[str, str]:
    """Extract env values from a script's parsed JSON, respecting env_mapping overrides."""
    values: dict[str, str] = {}
    mapping = link.env_mapping or {}
    for json_key, raw_value in parsed_json.items():
        if raw_value is None:
            continue
        value = str(raw_value)
        # Explicit override → target env var name
        target = mapping.get(json_key, json_key)
        values[target] = value
    return values


@router.post("/{deployment_id}/push", dependencies=_admin)
async def push_deployment(deployment_id: UUID):
    """Push generated docker-compose and .env to target servers via SSH.

    For each group in the deployment :
      1. Run all group_scripts with timing='before' on their designated machines,
         parse the last JSON line of stdout, and merge the values into the .env.
      2. Write compose + env on the group's target machine and docker compose up.
      3. Run all group_scripts with timing='after'.
    """
    try:
        deployment = await project_deployments_service.get_by_id(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if deployment.status != "generated" or not deployment.generated_compose:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deployment not generated yet")

    project = await projects_service.get_by_id(deployment.project_id)
    project_slug = project.display_name.lower().replace(" ", "-")

    results: list[dict[str, Any]] = []
    script_results: list[dict[str, Any]] = []

    # ─── Phase 1 : before-scripts (collect env merges) ─────────
    collected_env: dict[str, str] = {}
    group_ids_in_deploy = [UUID(gid) for gid in deployment.group_servers.keys()]
    before_links: list[Any] = []
    after_links: list[Any] = []
    for gid in group_ids_in_deploy:
        for link in await group_scripts_service.list_by_group(gid):
            if link.timing == "before":
                before_links.append(link)
            else:
                after_links.append(link)
    before_links.sort(key=lambda link: link.position)
    after_links.sort(key=lambda link: link.position)

    for link in before_links:
        try:
            script = await scripts_service.get_by_id(link.script_id)
        except scripts_service.ScriptNotFoundError:
            continue
        res = await _run_group_script(link, script.content)
        script_results.append(res)
        if res.get("success"):
            parsed = _parse_last_json(res.get("stdout", ""))
            if parsed:
                for k, v in _collect_env_from_script(link, parsed).items():
                    collected_env[k] = v

    if collected_env:
        env_text = _merge_env_with_values(deployment.generated_env or "", collected_env)
    else:
        env_text = deployment.generated_env or ""

    # Get unique machine IDs from group_servers (legacy JSONB key name kept — values are machine IDs)
    machine_ids = set(deployment.group_servers.values())

    for machine_id_str in machine_ids:
        machine_id = UUID(machine_id_str)
        try:
            machine = await infra_machines_service.get_by_id(machine_id)
            creds = await infra_machines_service.get_credentials(machine_id)
        except Exception as exc:
            results.append({"server": machine_id_str, "success": False, "error": str(exc)})
            continue

        private_key = None
        passphrase = None
        if creds.get("certificate_id"):
            cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
            private_key = cert.get("private_key")
            passphrase = cert.get("passphrase")

        # Tilde expansion : ecrit dans /home/<ssh_user>/ pour agflow,
        # ou /root/ si l'utilisateur SSH est root.
        remote_dir = f"~/agflow.docker/projects/{project_slug}"

        # Steps separes : chaque exec SSH = une operation atomique.
        # Le contenu des fichiers est passe en stdin (`cat > path`), pas en
        # heredoc dans la ligne de commande, pour eviter tout shell-escape.
        steps: list[tuple[str, str, str | None]] = [
            ("mkdir", f"mkdir -p {remote_dir}", None),
            ("write_compose", f"cat > {remote_dir}/docker-compose.yml", deployment.generated_compose or ""),
            ("write_env", f"cat > {remote_dir}/.env", env_text),
            ("compose_up", f"cd {remote_dir} && docker compose up -d", None),
        ]

        ssh_kwargs = {
            "host": creds["host"], "port": creds["port"],
            "username": creds["username"], "password": creds["password"],
            "private_key": private_key, "passphrase": passphrase,
        }

        step_result: dict[str, Any] = {}
        failed_step: str | None = None
        try:
            for step_name, cmd, stdin in steps:
                step_result = await ssh_executor.exec_command(
                    **ssh_kwargs, command=cmd, input=stdin,
                )
                if step_result.get("exit_code") != 0:
                    failed_step = step_name
                    break
        except Exception as exc:
            results.append({"server": machine.name or machine.host, "success": False, "error": str(exc)})
            continue

        results.append({
            "server": machine.name or machine.host,
            "success": failed_step is None,
            "step": failed_step,
            "stdout": step_result.get("stdout", ""),
            "stderr": step_result.get("stderr", ""),
        })

    # ─── Phase 3 : after-scripts (logged, no env merge) ────────
    for link in after_links:
        try:
            script = await scripts_service.get_by_id(link.script_id)
        except scripts_service.ScriptNotFoundError:
            continue
        res = await _run_group_script(link, script.content)
        script_results.append(res)

    # Update status to deployed if all deploy steps + all scripts succeeded
    all_deploys_ok = all(r.get("success") for r in results)
    all_scripts_ok = all(r.get("success") for r in script_results)
    if all_deploys_ok and all_scripts_ok:
        from agflow.db.pool import execute

        await execute(
            "UPDATE project_deployments SET status = 'deployed' WHERE id = $1",
            deployment_id,
        )

    return {"results": results, "scripts": script_results, "collected_env_keys": list(collected_env.keys())}


@router.delete("/{deployment_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_admin)
async def delete_deployment(deployment_id: UUID):
    try:
        await project_deployments_service.delete(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
