"""Project deployments service — asyncpg CRUD + generation."""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.products import DeploymentSummary, DeploymentStatus, StepLog
from agflow.services import (
    compose_renderer_service,
    groups_service,
    image_registries_service,
    product_catalog_service,
    product_instances_service,
    secrets_service,
)

_log = structlog.get_logger(__name__)


def _generate_secret_value(method: str) -> str:
    """Generate a secret value from a method string like random_hex(64) or random_base64(24)."""
    m = re.match(r"random_hex\((\d+)\)", method)
    if m:
        n = int(m.group(1))
        return os.urandom(n // 2 + 1).hex()[:n]

    m = re.match(r"random_base64\((\d+)\)", method)
    if m:
        n = int(m.group(1))
        return base64.urlsafe_b64encode(os.urandom(n)).decode()[:n + 4]

    return ""


_COLS = (
    "id, project_id, user_id, group_servers, status, current_step_index, "
    "accumulated_env, step_logs, generated_compose, generated_env, "
    "generated_secrets, nullable_secrets, generated_data, created_at, updated_at"
)


def _json_field(row: dict, key: str, default: Any) -> Any:
    v = row.get(key)
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return default


class DeploymentNotFoundError(Exception):
    pass


def _to_summary(row: dict[str, Any]) -> DeploymentSummary:
    gs = row.get("group_servers") or {}
    return DeploymentSummary(
        id=row["id"],
        project_id=row["project_id"],
        user_id=row["user_id"],
        group_servers=gs if isinstance(gs, dict) else json.loads(gs or "{}"),
        status=row.get("status") or "draft",
        current_step_index=row.get("current_step_index") or 0,
        accumulated_env=_json_field(row, "accumulated_env", {}),
        step_logs=[StepLog(**s) for s in _json_field(row, "step_logs", [])],
        generated_compose=row.get("generated_compose"),
        generated_env=row.get("generated_env"),
        generated_secrets=_json_field(row, "generated_secrets", {}),
        nullable_secrets=_json_field(row, "nullable_secrets", []),
        generated_data=_json_field(row, "generated_data", {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_by_project(project_id: UUID) -> list[DeploymentSummary]:
    rows = await fetch_all(
        f"SELECT {_COLS} FROM project_deployments WHERE project_id = $1 ORDER BY created_at DESC",
        project_id,
    )
    return [_to_summary(r) for r in rows]


async def list_by_user(user_id: UUID) -> list[DeploymentSummary]:
    rows = await fetch_all(
        f"SELECT {_COLS} FROM project_deployments WHERE user_id = $1 ORDER BY created_at DESC",
        user_id,
    )
    return [_to_summary(r) for r in rows]


async def get_by_id(deployment_id: UUID) -> DeploymentSummary:
    row = await fetch_one(
        f"SELECT {_COLS} FROM project_deployments WHERE id = $1",
        deployment_id,
    )
    if row is None:
        raise DeploymentNotFoundError(f"Deployment {deployment_id} not found")
    return _to_summary(row)


async def create(
    project_id: UUID,
    user_id: UUID,
    group_servers: dict[str, str] | None = None,
) -> DeploymentSummary:
    row = await fetch_one(
        f"""
        INSERT INTO project_deployments (project_id, user_id, group_servers)
        VALUES ($1, $2, $3::jsonb)
        RETURNING {_COLS}
        """,
        project_id, user_id, json.dumps(group_servers or {}),
    )
    assert row is not None
    _log.info("deployments.create", project_id=str(project_id), user_id=str(user_id))
    return _to_summary(row)


async def update_group_servers(deployment_id: UUID, group_servers: dict[str, str]) -> DeploymentSummary:
    await execute(
        "UPDATE project_deployments SET group_servers = $1::jsonb WHERE id = $2",
        json.dumps(group_servers), deployment_id,
    )
    return await get_by_id(deployment_id)


async def delete(deployment_id: UUID) -> None:
    row = await fetch_one(
        "DELETE FROM project_deployments WHERE id = $1 RETURNING id",
        deployment_id,
    )
    if row is None:
        raise DeploymentNotFoundError(f"Deployment {deployment_id} not found")
    _log.info("deployments.delete", id=str(deployment_id))


# ── Generation ──────────────────────────────────────────────


async def generate(deployment_id: UUID, user_secrets: dict[str, str] | None = None) -> DeploymentSummary:
    """Generate docker-compose YAML and .env for this deployment.

    user_secrets: decrypted user secrets from the frontend vault (highest priority).
    """
    deployment = await get_by_id(deployment_id)
    groups = await groups_service.list_by_project(deployment.project_id)

    # Load existing generated secrets (persist across regenerations)
    gen_secrets: dict[str, str] = dict(deployment.generated_secrets)

    # Load platform secrets from vault
    try:
        all_secrets = await secrets_service.list_all()
        vault: dict[str, str] = (
            await secrets_service.resolve_env([s.name for s in all_secrets])
            if all_secrets
            else {}
        )
    except Exception:
        vault = {}

    # User secrets are client-side encrypted — decrypted values are passed
    # by the frontend in the generate request (highest priority).
    u_secrets = user_secrets or {}

    all_instances = []
    for g in groups:
        instances = await product_instances_service.list_by_group(g.id)
        all_instances.extend(instances)

    # Pass 0: scan all products for secrets_required with generate methods
    # Generate missing values and persist them
    nullable_secrets: list[str] = []
    for inst in all_instances:
        try:
            detail = product_catalog_service.get_by_id(inst.catalog_id)
        except Exception:
            continue
        for s in detail.recipe.get("secrets_required", []):
            name = s.get("name", "")
            if not name:
                continue
            method = s.get("generate")
            # YAML `generate: null` -> Python None : secret nullable (optionnel,
            # peut rester vide ; ex. tokens API crees post-deploiement).
            if "generate" in s and method is None:
                nullable_secrets.append(name)
                continue
            if not method:
                continue
            # Already generated or in vault → skip
            if name in gen_secrets or name in vault:
                continue
            # Generate and store
            value = _generate_secret_value(method)
            if value:
                gen_secrets[name] = value
                _log.info("deployments.secret_generated", name=name, method=method)

    # Build the enriched data structure (recipe services + injected labels +
    # resolved placeholders). This is what the Deploy dialog displays for
    # validation; the actual docker-compose.yml generation is deferred.
    generated_data, env_refs = await compose_renderer_service.build_deployment_data(
        deployment.project_id,
    )

    # Also resolve ${VAR} refs from image_registries.credential_ref so that
    # registry credentials needed for ``docker login`` at push time are
    # materialized into the .env. Without this, user-vault secrets would
    # never reach the remote machine.
    try:
        for reg in image_registries_service.list_all():
            if not reg.credential_ref:
                continue
            for ref in re.findall(r"\$\{([A-Z_][A-Z0-9_]*)\}", reg.credential_ref):
                if ref not in env_refs:
                    env_refs.append(ref)
    except Exception as exc:
        _log.warning("deployments.registry_ref_scan_failed", error=str(exc))

    # Resolve each ${VAR} ref found in the data against the available sources
    # (priority: user > generated > vault). Unresolved refs become empty
    # placeholders so operators can see which ones are missing.
    env_vars: dict[str, str] = {}
    for ref in env_refs:
        if ref in u_secrets:
            env_vars[ref] = u_secrets[ref]
        elif ref in gen_secrets:
            env_vars[ref] = gen_secrets[ref]
        elif ref in vault:
            env_vars[ref] = vault[ref]
        else:
            env_vars[ref] = ""

    # Inject group-level variables into the .env. Each variable can be either
    # a literal value or a reference (${vault://…}, ${env://…}) that we resolve
    # via platform_secrets_service before writing.
    # The variable name (left-hand side) is used as-is for the .env key.
    try:
        from agflow.services import group_variables_service, platform_secrets_service
        platform_secrets_map = await platform_secrets_service.resolve_all()
        for g in groups:
            for var in await group_variables_service.list_by_group(g.id):
                resolved = platform_secrets_service.resolve_platform_refs(
                    var.value, platform_secrets_map,
                )
                env_vars[var.name] = resolved
    except Exception as exc:
        _log.warning("deployments.group_variables_inject_failed", error=str(exc))

    env_content = "\n".join(f"{k}={env_vars[k]}" for k in sorted(env_vars.keys()))

    # Store in DB
    unique_nullable = sorted(set(nullable_secrets))
    await execute(
        """
        UPDATE project_deployments
        SET generated_data = $1::jsonb, generated_env = $2, generated_secrets = $3::jsonb,
            nullable_secrets = $4::jsonb, status = 'generated'
        WHERE id = $5
        """,
        json.dumps(generated_data), env_content,
        json.dumps(gen_secrets), json.dumps(unique_nullable), deployment_id,
    )

    _log.info(
        "deployments.generated",
        id=str(deployment_id),
        env_refs=len(env_vars),
        groups=len(generated_data.get("groups", [])),
    )
    return await get_by_id(deployment_id)


# ── Wizard helpers ───────────────────────────────────────────


async def set_status(deployment_id: UUID, new_status: DeploymentStatus) -> None:
    await execute(
        "UPDATE project_deployments SET status = $1, updated_at = now() WHERE id = $2",
        new_status, deployment_id,
    )


async def advance_step(
    deployment_id: UUID,
    new_accumulated_env: dict[str, Any],
    new_log: dict[str, Any],
    next_status: DeploymentStatus,
) -> DeploymentSummary:
    """Ajoute un step_log, met à jour accumulated_env, avance current_step_index."""
    current = await get_by_id(deployment_id)
    logs = [s.model_dump() for s in current.step_logs] + [new_log]
    merged_env = {**current.accumulated_env, **new_accumulated_env}
    await execute(
        """
        UPDATE project_deployments
        SET status = $1,
            current_step_index = current_step_index + 1,
            accumulated_env = $2::jsonb,
            step_logs = $3::jsonb,
            updated_at = now()
        WHERE id = $4
        """,
        next_status, json.dumps(merged_env), json.dumps(logs), deployment_id,
    )
    return await get_by_id(deployment_id)


async def reset_to_executing(deployment_id: UUID) -> DeploymentSummary:
    """Retry : repasse à executing_step sans changer current_step_index."""
    await execute(
        "UPDATE project_deployments SET status = 'executing_step', updated_at = now() WHERE id = $1",
        deployment_id,
    )
    return await get_by_id(deployment_id)


async def get_ordered_before_scripts(deployment_id: UUID) -> list[Any]:
    """Retourne les group_scripts timing='before' triés par position."""
    from agflow.services import group_scripts_service
    deployment = await get_by_id(deployment_id)
    group_ids = [UUID(gid) for gid in deployment.group_servers.keys()]
    links: list[Any] = []
    for gid in group_ids:
        for link in await group_scripts_service.list_by_group(gid):
            if link.timing == "before":
                links.append(link)
    return sorted(links, key=lambda l: l.position)
