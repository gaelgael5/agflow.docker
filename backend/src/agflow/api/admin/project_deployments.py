from __future__ import annotations

import asyncio
import json as _json
import re
import secrets
import shlex
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import structlog
import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.products import (
    DeploymentCreate,
    DeploymentSummary,
    DeploymentUpdate,
    GenerateRequest,
)
from agflow.services import (
    compose_renderer_service,
    deployment_executor,
    group_scripts_service,
    groups_service,
    image_registries_service,
    infra_certificates_service,
    infra_machines_service,
    product_instances_service,
    project_deployments_service,
    project_runtimes_service,
    projects_service,
    scripts_service,
    secrets_service,
    ssh_executor,
    swarm_deploy_steps,
    users_service,
)
from agflow.services.deployment_env_helpers import (
    collect_env_from_script as _collect_env_from_script,
)
from agflow.services.deployment_env_helpers import (
    evaluate_trigger_rules as _evaluate_trigger_rules,
)
from agflow.services.deployment_env_helpers import (
    merge_env_with_values as _merge_env_with_values,
)
from agflow.services.deployment_env_helpers import (
    parse_env_map as _parse_env_map,
)
from agflow.services.deployment_env_helpers import (
    parse_last_json as _parse_last_json,
)
from agflow.services.deployment_env_helpers import (
    resolve_input_value as _resolve_input_value,
)
from agflow.services.deployment_env_helpers import (
    ssh_kwargs_for_machine as _ssh_kwargs_for_machine,
)
from agflow.services.deployment_env_helpers import (
    substitute_script_placeholders as _substitute_script_placeholders,
)
from agflow.services.deployment_log_bus import log_bus

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


@router.post("/{deployment_id}/generate", response_model=DeploymentSummary, dependencies=_admin)
async def generate_deployment(deployment_id: UUID, payload: GenerateRequest | None = None):
    try:
        return await project_deployments_service.generate(
            deployment_id,
            user_secrets=payload.user_secrets if payload else None,
            group_vars=payload.group_vars if payload else None,
        )
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{deployment_id}/groups/{group_id}/compose",
    dependencies=_admin,
)
async def get_group_compose(deployment_id: UUID, group_id: UUID) -> dict[str, str]:
    """Render the docker-compose YAML for one group using its Jinja template."""
    try:
        deployment = await project_deployments_service.get_by_id(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    try:
        rendered = await compose_renderer_service.render_group_compose(
            deployment.generated_data, group_id,
        )
    except compose_renderer_service.ComposeRenderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"compose": rendered}


_REG_HOST_RE = re.compile(r"^([a-zA-Z0-9.-]+(?::\d+)?)\/")


def _image_registry_host(image: str) -> str:
    """Return the registry host of a docker image. Defaults to docker.io.

    A registry host must appear before a ``/`` and contain ``.``, ``:`` (port),
    or be the literal ``localhost`` — otherwise the first segment is a Docker Hub
    namespace (e.g., ``library/postgres``) rather than a registry.
    """
    first, sep, _rest = image.partition("/")
    if not sep:
        return "docker.io"
    if "." in first or ":" in first or first == "localhost":
        return first
    return "docker.io"


def _extract_compose_images(compose_yaml: str) -> list[str]:
    try:
        data = yaml.safe_load(compose_yaml or "") or {}
    except yaml.YAMLError:
        return []
    images: list[str] = []
    services = data.get("services", {}) if isinstance(data, dict) else {}
    if not isinstance(services, dict):
        return []
    for svc in services.values():
        if isinstance(svc, dict):
            img = svc.get("image")
            if isinstance(img, str) and img:
                images.append(img)
    return images


_REF_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _resolve_env_refs(value: str, env_map: dict[str, str]) -> str:
    """Replace ${VAR} in value with env_map[VAR]; literal text is kept as-is."""
    return _REF_RE.sub(lambda m: env_map.get(m.group(1), m.group(0)), value or "")


def _extract_ref_names(value: str) -> list[str]:
    return _REF_RE.findall(value or "")


class RegistryCredentialError(Exception):
    """Raised when a registry credential cannot be resolved for docker login."""


async def _build_registry_login_steps(
    compose_yaml: str,
    env_map: dict[str, str],
) -> list[tuple[str, str, str | None]]:
    """Build docker login steps for every registry in compose with stored credentials.

    Credential format: ``user:token`` (each side may be ``${VAR}`` or a literal).
    Variable refs are resolved against ``env_map`` first (deployment .env), then
    fall back to the server-side global secrets vault so registry credentials
    never need to leak into the remote .env file.

    Raises :class:`RegistryCredentialError` when a matching registry exists for
    an image host but its credential cannot be resolved (empty credential_ref,
    unresolved ``${VAR}`` reference, or missing token).
    """
    try:
        registries = image_registries_service.list_all()
    except Exception:
        return []

    # Index only registries that have stored credentials — others are assumed
    # public (no login needed). A registry without credential_ref is simply not
    # a candidate for auto-login.
    reg_by_host: dict[str, Any] = {}
    for reg in registries:
        if not reg.credential_ref:
            continue
        try:
            host = urlparse(reg.url).hostname or reg.url
        except Exception:
            continue
        if host:
            reg_by_host[host] = reg

    hosts_seen: set[str] = set()
    relevant_regs: list[Any] = []
    for img in _extract_compose_images(compose_yaml):
        host = _image_registry_host(img)
        if host in hosts_seen or host not in reg_by_host:
            continue
        hosts_seen.add(host)
        relevant_regs.append(reg_by_host[host])

    # Collect all ${VAR} refs that aren't resolved by env_map and fetch them
    # from the backend secrets vault in one round-trip.
    missing_refs: set[str] = set()
    for reg in relevant_regs:
        for name in _extract_ref_names(reg.credential_ref or ""):
            if name not in env_map:
                missing_refs.add(name)

    vault_map: dict[str, str] = {}
    for name in missing_refs:
        try:
            vault_map.update(await secrets_service.resolve_env([name]))
        except secrets_service.SecretNotFoundError:
            continue

    resolve_map = {**vault_map, **env_map}

    steps: list[tuple[str, str, str | None]] = []
    for reg in relevant_regs:
        host = urlparse(reg.url).hostname or reg.url
        resolved = _resolve_env_refs(reg.credential_ref, resolve_map).strip()
        unresolved = _extract_ref_names(resolved)
        if unresolved:
            raise RegistryCredentialError(
                f"Registry '{reg.id}' ({host}) credential references unresolved "
                f"secret(s): {', '.join('${' + r + '}' for r in unresolved)}. "
                f"Create them in Admin → Secrets (global scope) or Mes secrets, "
                f"then regenerate the deployment so they land in the .env."
            )
        if not resolved:
            raise RegistryCredentialError(
                f"Registry '{reg.id}' ({host}) credential_ref is empty after "
                f"resolution — check its value in Image Registries."
            )

        user, sep, token = resolved.partition(":")
        if not sep:
            user, token = "token", resolved
        if not token:
            raise RegistryCredentialError(
                f"Registry '{reg.id}' ({host}) credential has no token part. "
                f"Expected format: 'username:${{SECRET_NAME}}' (or a literal token)."
            )
        cmd = (
            f"docker login {shlex.quote(host)} "
            f"-u {shlex.quote(user)} --password-stdin"
        )
        steps.append((f"docker_login_{host}", cmd, token))
    return steps


async def _run_group_script(link: Any, script_content: str, env_text: str = "") -> dict[str, Any]:
    """Upload + exec a shell script on its target machine. Returns result dict.

    `env_text` is the deploy's .env content — used to resolve ${VAR} references
    inside link.input_values before substitution into the script content.
    """
    try:
        # `resolve_target_machine_id` retourne `link.machine_id` si target_kind=
        # 'fixed_machine', et `groups.machine_id` si target_kind='deployment_host'.
        target_machine_id = await group_scripts_service.resolve_target_machine_id(link.id)
        ssh = await _ssh_kwargs_for_machine(target_machine_id)
    except group_scripts_service.GroupScriptNoDeploymentHostError as exc:
        return {
            "script": link.script_name, "machine": link.machine_name,
            "timing": link.timing, "success": False, "error": str(exc),
        }
    except Exception as exc:
        return {
            "script": link.script_name, "machine": link.machine_name,
            "timing": link.timing, "success": False, "error": str(exc),
        }

    # Résolution en 2 étapes pour chaque input_value :
    #   1) ${vault://api:path} et ${env://NAME} → via platform_secrets_service
    #      (qui fait l'appel SDK Harpocrate + lecture table env globale)
    #   2) ${SIMPLE_NAME} → contre le .env du déploiement (qui contient
    #      maintenant les variables de groupe injectées au Generate)
    from agflow.services import platform_secrets_service
    platform_secrets_map = await platform_secrets_service.resolve_all()
    resolved_inputs: dict[str, str] = {}
    for name, raw in (link.input_values or {}).items():
        # Étape 1 : résoudre les refs déclaratives ${vault://…} / ${env://…}
        step1 = platform_secrets_service.resolve_platform_refs(
            raw or "", platform_secrets_map,
        )
        # Étape 2 : résoudre les ${VAR} simples contre le .env
        resolved, _ok = _resolve_input_value(step1, env_text)
        resolved_inputs[name] = resolved

    rendered = _substitute_script_placeholders(script_content, resolved_inputs)

    remote_path = f"/tmp/agflow-script-{secrets.token_hex(8)}.sh"
    try:
        await ssh_executor.exec_command(**ssh, command=f"cat > {remote_path}", input=rendered)
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


@router.post("/{deployment_id}/push")
async def push_deployment(deployment_id: UUID, user_id: UUID = Depends(_get_user_id)):
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

    if deployment.status != "generated":
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
        # Evaluate trigger rules against the current .env (with already-collected values applied)
        current_env_text = _merge_env_with_values(deployment.generated_env or "", collected_env)
        ok, reason = _evaluate_trigger_rules(link.trigger_rules, _parse_env_map(current_env_text))
        if not ok:
            script_results.append({
                "script": link.script_name, "machine": link.machine_name,
                "timing": link.timing, "position": link.position,
                "skipped": True, "reason": reason, "success": True, "exit_code": 0,
            })
            continue
        res = await _run_group_script(link, script.content, env_text=current_env_text)
        script_results.append(res)
        if res.get("success"):
            parsed = _parse_last_json(res.get("stdout", ""))
            if parsed:
                for k, v in _collect_env_from_script(
                    link, parsed, _parse_env_map(current_env_text),
                ).items():
                    collected_env[k] = v

    # Create a project_runtime + one project_group_runtime per (group, machine).
    # The group_runtime UUID is injected as `{GROUP_SLUG}_RUNTIME_ID` in the .env
    # so docker-compose interpolates it into the `agflow.runtime_id` label of
    # every service of that group.
    project_runtime_id, project_runtime_seq = await project_runtimes_service.upsert_project_runtime(
        project_id=deployment.project_id,
        deployment_id=deployment.id,
        user_id=user_id,
    )
    collected_env["PROJECT_RUNTIME_SEQ"] = str(project_runtime_seq)
    project_groups = await groups_service.list_by_project(deployment.project_id)
    groups_by_id = {str(g.id): g for g in project_groups}
    group_runtime_ids: dict[str, UUID] = {}
    for gid_str, mid_str in deployment.group_servers.items():
        try:
            gid = UUID(gid_str)
            mid = UUID(mid_str) if mid_str else None
        except Exception:
            continue
        runtime_id = await project_runtimes_service.upsert_group_runtime(
            project_runtime_id=project_runtime_id,
            group_id=gid,
            machine_id=mid,
        )
        group_runtime_ids[gid_str] = runtime_id
        group = groups_by_id.get(gid_str)
        if group:
            slug = re.sub(r"[^A-Z0-9]", "_", (group.name or "").upper())
            collected_env[f"{slug}_RUNTIME_ID"] = str(runtime_id)

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
        # Suffixé par le seq du project_runtime pour garder chaque déploiement
        # isolé (permet rollback / coexistence de plusieurs versions).
        remote_dir = f"~/agflow.docker/projects/{project_slug}-{project_runtime_seq}"

        # Render the compose for every group assigned to this machine, using each
        # group's Jinja template. Simple concat for now (one-group-per-machine is
        # the nominal case); proper YAML merge can be added if needed.
        group_ids_on_machine = [
            UUID(gid) for gid, mid in deployment.group_servers.items()
            if mid == str(machine_id)
        ]
        compose_fragments: list[str] = []
        render_failed: str | None = None
        for gid in group_ids_on_machine:
            try:
                fragment = await compose_renderer_service.render_group_compose(
                    deployment.generated_data, gid,
                )
            except compose_renderer_service.ComposeRenderError as exc:
                render_failed = str(exc)
                break
            compose_fragments.append(fragment)
        if render_failed is not None:
            results.append({
                "server": machine.name or machine.host,
                "machine_id": str(machine_id),
                "success": False,
                "error": render_failed,
            })
            continue
        compose_content = "\n".join(compose_fragments)

        # Steps separes : chaque exec SSH = une operation atomique.
        # Le contenu des fichiers est passe en stdin (`cat > path`), pas en
        # heredoc dans la ligne de commande, pour eviter tout shell-escape.
        try:
            login_steps = await _build_registry_login_steps(
                compose_content,
                _parse_env_map(env_text),
            )
        except RegistryCredentialError as exc:
            results.append({
                "server": machine.name or machine.host,
                "machine_id": str(machine_id),
                "success": False,
                "error": str(exc),
            })
            continue
        stack_name = f"agflow-proj-{project_slug}-{project_runtime_seq}"
        steps = swarm_deploy_steps.build_deploy_steps(
            remote_dir=remote_dir,
            compose_content=compose_content,
            env_content=env_text,
            stack_name=stack_name,
            extra_steps_before_deploy=login_steps,
        )

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
            "machine_id": str(machine_id),
            "success": failed_step is None,
            "step": failed_step,
            "stdout": step_result.get("stdout", ""),
            "stderr": step_result.get("stderr", ""),
        })

        # Update the runtime rows for all groups assigned to this machine
        for gid_str, mid_str in deployment.group_servers.items():
            if mid_str != str(machine_id):
                continue
            rid = group_runtime_ids.get(gid_str)
            if rid is None:
                continue
            await project_runtimes_service.update_group_runtime_push(
                runtime_id=rid,
                env_text=env_text,
                compose_yaml=compose_content,
                remote_path=remote_dir,
                status="deployed" if failed_step is None else "failed",
                error_message=None if failed_step is None else f"failed at step {failed_step}: {step_result.get('stderr', '')[:500]}",
            )

    # ─── Phase 3 : after-scripts (logged, no env merge) ────────
    final_env_text = env_text
    for link in after_links:
        try:
            script = await scripts_service.get_by_id(link.script_id)
        except scripts_service.ScriptNotFoundError:
            continue
        ok, reason = _evaluate_trigger_rules(link.trigger_rules, _parse_env_map(final_env_text))
        if not ok:
            script_results.append({
                "script": link.script_name, "machine": link.machine_name,
                "timing": link.timing, "position": link.position,
                "skipped": True, "reason": reason, "success": True, "exit_code": 0,
            })
            continue
        res = await _run_group_script(link, script.content, env_text=final_env_text)
        script_results.append(res)

    # Record each deployed instance in the pivot table. Machines are keyed by
    # group_id in deployment.group_servers. Each group's instances land on that
    # machine.
    from agflow.db.pool import execute

    for group_id_str, machine_id_str in deployment.group_servers.items():
        try:
            group_uuid = UUID(group_id_str)
            machine_uuid = UUID(machine_id_str)
        except Exception:
            continue
        # Find deploy result for this machine (if any)
        machine_result = next(
            (r for r in results if r.get("success") is not None
             and (r.get("server") or "") in {str(machine_uuid), ""}),
            None,
        )
        success_flag = machine_result.get("success") if machine_result else True
        error_msg = None
        if machine_result and not machine_result.get("success"):
            error_msg = machine_result.get("error") or machine_result.get("stderr")
        for inst in await product_instances_service.list_by_group(group_uuid):
            await execute(
                """
                INSERT INTO deployment_instances
                    (deployment_id, instance_id, machine_id, success, error_message)
                VALUES ($1, $2, $3, $4, $5)
                """,
                deployment_id, inst.id, machine_uuid, success_flag, error_msg,
            )

    # Update status to deployed if all deploy steps + all scripts succeeded
    all_deploys_ok = all(r.get("success") for r in results)
    all_scripts_ok = all(r.get("success") for r in script_results)
    if all_deploys_ok and all_scripts_ok:
        await execute(
            "UPDATE project_deployments SET status = 'deployed' WHERE id = $1",
            deployment_id,
        )
        await project_runtimes_service.update_project_runtime_status(
            project_runtime_id, "deployed",
        )
    else:
        await project_runtimes_service.update_project_runtime_status(
            project_runtime_id, "failed",
            error_message="one or more groups or scripts failed",
        )

    return {
        "results": results,
        "scripts": script_results,
        "collected_env_keys": list(collected_env.keys()),
        "project_runtime_id": str(project_runtime_id),
    }


def _log_task_exception(dep_id: UUID, task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _log.error("step_task_crashed", deployment_id=str(dep_id), exc_info=exc)
        asyncio.create_task(project_deployments_service.set_status(dep_id, "step_failed"))


@router.post(
    "/{deployment_id}/execute-step",
    dependencies=_admin,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_step_endpoint(deployment_id: UUID) -> dict[str, str]:
    """Lance l'exécution du step courant en tâche asyncio. Retourne 202 immédiatement."""
    try:
        deployment = await project_deployments_service.get_by_id(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    allowed = {"generated", "step_complete"}
    if deployment.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot execute step from status '{deployment.status}'. Expected: {allowed}",
        )

    await project_deployments_service.set_status(deployment_id, "executing_step")
    task = asyncio.create_task(deployment_executor.execute_step(deployment_id))
    task.add_done_callback(lambda t: _log_task_exception(deployment_id, t))
    return {"status": "accepted"}


@router.post(
    "/{deployment_id}/retry-step",
    dependencies=_admin,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_step_endpoint(deployment_id: UUID) -> dict[str, str]:
    """Réessaie le step courant (status doit être step_failed)."""
    try:
        deployment = await project_deployments_service.get_by_id(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if deployment.status != "step_failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot retry from status '{deployment.status}'. Expected: step_failed",
        )

    await project_deployments_service.reset_to_executing(deployment_id)
    task = asyncio.create_task(deployment_executor.execute_step(deployment_id))
    task.add_done_callback(lambda t: _log_task_exception(deployment_id, t))
    return {"status": "accepted"}


@router.get("/{deployment_id}/stream", dependencies=_admin)
async def stream_deployment_logs(deployment_id: UUID) -> StreamingResponse:
    """SSE : stream des logs du step en cours.

    Format des events :
      data: {"type": "log", "line": "...", "stream": "stdout"}
      data: {"type": "step_complete", "step_index": 0, "output_vars": {...}}
      data: {"type": "step_failed", "step_index": 0, "exit_code": 1}
      data: {"type": "before_complete"}
    """
    try:
        await project_deployments_service.get_by_id(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    async def event_generator():
        q = log_bus.subscribe(deployment_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield 'data: {"type": "keepalive"}\n\n'
                    continue
                if event is None:
                    break
                yield f"data: {_json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            log_bus.unsubscribe(deployment_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{deployment_id}/deploy")
async def deploy_endpoint(deployment_id: UUID, user_id: UUID = Depends(_get_user_id)):
    """Déploiement final SSH (docker-compose / stack) après before_complete.

    Reprend la logique de push mais part de accumulated_env déjà construit
    par les before-scripts.
    """
    try:
        deployment = await project_deployments_service.get_by_id(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if deployment.status != "before_complete":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot deploy from status '{deployment.status}'. Expected: before_complete",
        )

    await project_deployments_service.set_status(deployment_id, "deploying")

    # Env final = generated_env + accumulated_env (accumulé par les before-scripts)
    accumulated = {k: str(v) for k, v in deployment.accumulated_env.items()}
    env_text = _merge_env_with_values(deployment.generated_env or "", accumulated)

    project = await projects_service.get_by_id(deployment.project_id)
    project_slug = project.display_name.lower().replace(" ", "-")

    results: list[dict[str, Any]] = []

    # Créer project_runtime + group_runtimes
    collected_env: dict[str, str] = {**accumulated}
    project_runtime_id, project_runtime_seq = await project_runtimes_service.upsert_project_runtime(
        project_id=deployment.project_id,
        deployment_id=deployment.id,
        user_id=user_id,
    )
    collected_env["PROJECT_RUNTIME_SEQ"] = str(project_runtime_seq)

    project_groups = await groups_service.list_by_project(deployment.project_id)
    groups_by_id = {str(g.id): g for g in project_groups}
    group_runtime_ids: dict[str, Any] = {}
    for gid_str, mid_str in deployment.group_servers.items():
        try:
            gid = UUID(gid_str)
            mid = UUID(mid_str) if mid_str else None
        except Exception:
            continue
        runtime_id = await project_runtimes_service.upsert_group_runtime(
            project_runtime_id=project_runtime_id, group_id=gid, machine_id=mid,
        )
        group_runtime_ids[gid_str] = runtime_id
        group = groups_by_id.get(gid_str)
        if group:
            slug = re.sub(r"[^A-Z0-9]", "_", (group.name or "").upper())
            collected_env[f"{slug}_RUNTIME_ID"] = str(runtime_id)

    env_text = _merge_env_with_values(env_text, collected_env)

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

        remote_dir = f"~/agflow.docker/projects/{project_slug}-{project_runtime_seq}"
        group_ids_on_machine = [
            UUID(gid) for gid, mid in deployment.group_servers.items()
            if mid == str(machine_id)
        ]
        compose_fragments: list[str] = []
        render_failed: str | None = None
        for gid in group_ids_on_machine:
            try:
                fragment = await compose_renderer_service.render_group_compose(deployment.generated_data, gid)
            except compose_renderer_service.ComposeRenderError as exc:
                render_failed = str(exc)
                break
            compose_fragments.append(fragment)
        if render_failed is not None:
            results.append({
                "server": machine.name or machine.host,
                "machine_id": str(machine_id),
                "success": False,
                "error": render_failed,
            })
            continue
        compose_content = "\n".join(compose_fragments)

        try:
            login_steps = await _build_registry_login_steps(compose_content, _parse_env_map(env_text))
        except RegistryCredentialError as exc:
            results.append({
                "server": machine.name or machine.host,
                "machine_id": str(machine_id),
                "success": False,
                "error": str(exc),
            })
            continue

        stack_name = f"agflow-proj-{project_slug}-{project_runtime_seq}"
        steps = swarm_deploy_steps.build_deploy_steps(
            remote_dir=remote_dir, compose_content=compose_content,
            env_content=env_text, stack_name=stack_name,
            extra_steps_before_deploy=login_steps,
        )
        ssh_kwargs = {
            "host": creds["host"], "port": creds["port"],
            "username": creds["username"], "password": creds["password"],
            "private_key": private_key, "passphrase": passphrase,
        }

        step_result: dict[str, Any] = {}
        failed_step: str | None = None
        try:
            for step_name, cmd, stdin in steps:
                step_result = await ssh_executor.exec_command(**ssh_kwargs, command=cmd, input=stdin)
                if step_result.get("exit_code") != 0:
                    failed_step = step_name
                    break
        except Exception as exc:
            results.append({"server": machine.name or machine.host, "success": False, "error": str(exc)})
            continue

        results.append({
            "server": machine.name or machine.host,
            "machine_id": str(machine_id),
            "success": failed_step is None,
            "step": failed_step,
        })

        for gid_str, mid_str in deployment.group_servers.items():
            if mid_str != str(machine_id):
                continue
            rid = group_runtime_ids.get(gid_str)
            if rid is None:
                continue
            await project_runtimes_service.update_group_runtime_push(
                runtime_id=rid, env_text=env_text, compose_yaml=compose_content,
                remote_path=remote_dir,
                status="deployed" if failed_step is None else "failed",
                error_message=None if failed_step is None else f"failed at step {failed_step}",
            )

    # After-scripts
    group_ids_in_deploy = [UUID(gid) for gid in deployment.group_servers]
    after_links: list[Any] = []
    for gid in group_ids_in_deploy:
        for link in await group_scripts_service.list_by_group(gid):
            if link.timing == "after":
                after_links.append(link)
    after_links.sort(key=lambda lnk: lnk.position)
    for link in after_links:
        try:
            script = await scripts_service.get_by_id(link.script_id)
            await _run_group_script(link, script.content, env_text=env_text)
        except Exception:
            pass

    all_ok = all(r.get("success") for r in results)
    final_status = "deployed" if all_ok else "failed"
    await project_deployments_service.set_status(deployment_id, final_status)
    await project_runtimes_service.update_project_runtime_status(
        project_runtime_id, final_status,
        error_message=None if all_ok else "one or more machines failed",
    )

    return {"results": results, "status": final_status}


@router.get("/{deployment_id}/before-steps", dependencies=_admin)
async def get_before_steps(deployment_id: UUID) -> list[dict[str, Any]]:
    """Retourne les group_scripts before ordonnés, avec machine et input vars."""
    try:
        await project_deployments_service.get_by_id(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    links = await project_deployments_service.get_ordered_before_scripts(deployment_id)
    return [
        {
            "script_name": link.script_name,
            "machine_name": link.machine_name,
            "position": link.position,
            "timing": link.timing,
            "input_variables": [
                {"name": k, "resolved": bool(v)}
                for k, v in (link.input_values or {}).items()
            ],
        }
        for link in links
    ]


@router.delete("/{deployment_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_admin)
async def delete_deployment(deployment_id: UUID):
    try:
        await project_deployments_service.delete(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
