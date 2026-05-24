"""Executor de scripts before-deploy step-by-step.

Chaque appel à `execute_step` tourne dans une tâche asyncio.
Il publie ses logs dans le `log_bus` (consommé par le SSE endpoint)
et met à jour la table `project_deployments` (status, accumulated_env, step_logs).
"""
from __future__ import annotations

import contextlib
import json as _json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute as db_execute
from agflow.services import project_deployments_service, scripts_service, ssh_executor
from agflow.services.deployment_log_bus import log_bus

_log = structlog.get_logger(__name__)


async def _run_script_streaming(
    link: Any,
    script_content: str,
    env_text: str,
    on_line: Any,  # callable async (stream_type, line)
) -> dict[str, Any]:
    """Exécute un script SSH en streaming.

    Résout les input_values, substitue les placeholders, upload + exécute.
    Appelle `on_line(stream_type, line)` pour chaque ligne reçue.
    Retourne {success, exit_code, stdout, stderr}.
    """
    import secrets as _secrets

    from agflow.api.admin.project_deployments import (
        _resolve_input_value,
        _ssh_kwargs_for_machine,
        _substitute_script_placeholders,
    )
    from agflow.services import group_scripts_service, platform_secrets_service

    try:
        target_machine_id = await group_scripts_service.resolve_target_machine_id(link.id)
        ssh = await _ssh_kwargs_for_machine(target_machine_id)
    except Exception as exc:
        await on_line("stderr", str(exc))
        return {"success": False, "exit_code": -1, "stdout": "", "stderr": str(exc)}

    platform_secrets_map = await platform_secrets_service.resolve_all()
    resolved_inputs: dict[str, str] = {}
    for name, raw in (link.input_values or {}).items():
        step1 = platform_secrets_service.resolve_platform_refs(raw or "", platform_secrets_map)
        resolved, _ = _resolve_input_value(step1, env_text)
        resolved_inputs[name] = resolved

    rendered = _substitute_script_placeholders(script_content, resolved_inputs)
    remote_path = f"/tmp/agflow-script-{_secrets.token_hex(8)}.sh"

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    exit_code = -1

    try:
        await ssh_executor.exec_command(**ssh, command=f"cat > {remote_path}", input=rendered)
        await ssh_executor.exec_command(**ssh, command=f"chmod +x {remote_path}")

        async for stream_type, line in ssh_executor.exec_command_stream(**ssh, command=f"bash {remote_path}"):
            if stream_type == "exit":
                exit_code = int(line)
            elif stream_type == "stdout":
                stdout_lines.append(line)
                await on_line("stdout", line)
            else:
                stderr_lines.append(line)
                await on_line("stderr", line)
    except Exception as exc:
        await on_line("stderr", str(exc))
        return {"success": False, "exit_code": -1, "stdout": "", "stderr": str(exc)}
    finally:
        with contextlib.suppress(Exception):
            await ssh_executor.exec_command(**ssh, command=f"rm -f {remote_path}")

    return {
        "success": exit_code == 0,
        "exit_code": exit_code,
        "stdout": "\n".join(stdout_lines),
        "stderr": "\n".join(stderr_lines),
    }


async def execute_step(deployment_id: UUID) -> None:
    """Tâche asyncio — exécute le step courant et met à jour la DB.

    Appelée par `POST /{id}/execute-step` via `asyncio.create_task`.
    """
    from agflow.api.admin.project_deployments import (
        _collect_env_from_script,
        _evaluate_trigger_rules,
        _merge_env_with_values,
        _parse_env_map,
        _parse_last_json,
    )

    deployment = await project_deployments_service.get_by_id(deployment_id)
    before_scripts = await project_deployments_service.get_ordered_before_scripts(deployment_id)
    step_index = deployment.current_step_index

    if step_index >= len(before_scripts):
        await project_deployments_service.set_status(deployment_id, "before_complete")
        await log_bus.publish(deployment_id, {"type": "before_complete"})
        await log_bus.close(deployment_id)
        return

    link = before_scripts[step_index]

    try:
        script = await scripts_service.get_by_id(link.script_id)
    except scripts_service.ScriptNotFoundError:
        await project_deployments_service.set_status(deployment_id, "step_failed")
        await log_bus.publish(deployment_id, {
            "type": "step_failed", "step_index": step_index,
            "exit_code": -1, "error": "script not found",
        })
        await log_bus.close(deployment_id)
        return

    # Construire le texte d'env courant = generated_env + accumulated_env
    current_env = _merge_env_with_values(
        deployment.generated_env or "",
        {k: str(v) for k, v in deployment.accumulated_env.items()},
    )

    # Évaluer les trigger_rules
    ok, reason = _evaluate_trigger_rules(link.trigger_rules, _parse_env_map(current_env))
    if not ok:
        skipped_log = {
            "step_index": step_index, "lines": [f"[skipped] {reason}"],
            "exit_code": 0,
            "started_at": datetime.now(UTC).isoformat(),
            "ended_at": datetime.now(UTC).isoformat(),
        }
        await log_bus.publish(deployment_id, {"type": "log", "line": f"[skipped] {reason}", "stream": "info"})
        next_status = "before_complete" if step_index + 1 >= len(before_scripts) else "step_complete"
        await project_deployments_service.advance_step(
            deployment_id,
            new_accumulated_env={},
            new_log=skipped_log,
            next_status=next_status,
        )
        if next_status == "before_complete":
            await log_bus.publish(deployment_id, {"type": "before_complete"})
        else:
            await log_bus.publish(deployment_id, {"type": "step_complete", "step_index": step_index})
        await log_bus.close(deployment_id)
        return

    lines: list[str] = []
    started_at = datetime.now(UTC).isoformat()

    async def on_line(stream_type: str, line: str) -> None:
        lines.append(line)
        await log_bus.publish(deployment_id, {"type": "log", "line": line, "stream": stream_type})

    await log_bus.publish(deployment_id, {"type": "step_start", "step_index": step_index, "script": link.script_name})
    result = await _run_script_streaming(link, script.content, current_env, on_line)
    ended_at = datetime.now(UTC).isoformat()

    step_log = {
        "step_index": step_index, "lines": lines,
        "exit_code": result["exit_code"],
        "started_at": started_at, "ended_at": ended_at,
    }

    if not result["success"]:
        await project_deployments_service.set_status(deployment_id, "step_failed")
        await log_bus.publish(deployment_id, {
            "type": "step_failed", "step_index": step_index,
            "exit_code": result["exit_code"],
        })
        # Stocker le log même en cas d'échec
        deployment2 = await project_deployments_service.get_by_id(deployment_id)
        logs = [s.model_dump() for s in deployment2.step_logs] + [step_log]
        await db_execute(
            "UPDATE project_deployments SET step_logs = $1::jsonb, updated_at = now() WHERE id = $2",
            _json.dumps(logs), deployment_id,
        )
        await log_bus.close(deployment_id)
        return

    # Succès : extraire les output vars
    parsed_json = _parse_last_json(result["stdout"])
    new_env_values: dict[str, str] = {}
    if parsed_json:
        env_map = _parse_env_map(current_env)
        new_env_values = _collect_env_from_script(link, parsed_json, env_map)

    next_status = "before_complete" if step_index + 1 >= len(before_scripts) else "step_complete"
    await project_deployments_service.advance_step(
        deployment_id,
        new_accumulated_env=new_env_values,
        new_log=step_log,
        next_status=next_status,
    )

    if next_status == "before_complete":
        await log_bus.publish(deployment_id, {"type": "before_complete"})
    else:
        await log_bus.publish(deployment_id, {
            "type": "step_complete", "step_index": step_index,
            "output_vars": new_env_values,
        })

    await log_bus.close(deployment_id)
