"""Project deployments service — asyncpg CRUD + generation."""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any
from uuid import UUID

import structlog
import yaml

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.products import DeploymentSummary
from agflow.services import (
    groups_service,
    product_catalog_service,
    product_instances_service,
    projects_service,
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


_COLS = "id, project_id, user_id, group_servers, status, generated_compose, generated_env, generated_secrets, nullable_secrets, created_at, updated_at"


class DeploymentNotFoundError(Exception):
    pass


def _to_summary(row: dict[str, Any]) -> DeploymentSummary:
    gs = row.get("group_servers") or {}
    if isinstance(gs, str):
        gs = json.loads(gs)
    gen_sec = row.get("generated_secrets") or {}
    if isinstance(gen_sec, str):
        gen_sec = json.loads(gen_sec)
    null_sec = row.get("nullable_secrets") or []
    if isinstance(null_sec, str):
        null_sec = json.loads(null_sec)
    return DeploymentSummary(
        id=row["id"],
        project_id=row["project_id"],
        user_id=row["user_id"],
        group_servers=gs,
        status=row["status"],
        generated_compose=row.get("generated_compose"),
        generated_env=row.get("generated_env"),
        generated_secrets=gen_sec,
        nullable_secrets=null_sec,
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
    project = await projects_service.get_by_id(deployment.project_id)
    groups = await groups_service.list_by_project(deployment.project_id)

    # Load existing generated secrets (persist across regenerations)
    gen_secrets: dict[str, str] = dict(deployment.generated_secrets)

    # Load platform secrets from vault
    try:
        all_secrets = await secrets_service.list_all()
        vault: dict[str, str] = {}
        for s in all_secrets:
            revealed = await secrets_service.reveal(s.id)
            vault[s.var_name] = revealed.value
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

    compose_services: dict[str, dict] = {}
    env_vars: dict[str, str] = {}

    for inst in all_instances:
        try:
            detail = product_catalog_service.get_by_id(inst.catalog_id)
        except Exception:
            continue

        recipe = detail.recipe
        user_vars = inst.variables or {}
        inst_name = inst.instance_name

        # Build resolution context
        pass1_ctx = {"_name": inst_name}

        pass2_ctx: dict[str, str] = {}
        pass2_ctx.update(user_vars)
        pass2_ctx["instance_name"] = inst_name
        pass2_ctx["instance_id"] = str(inst.id)
        pass2_ctx["_name"] = inst_name

        # Service hosts
        for svc in recipe.get("services", []):
            svc_id = svc.get("id", "")
            cn = f"{inst_name}-{svc_id}"
            pass2_ctx[f"services.{svc_id}.host"] = cn
            pass2_ctx[f"services.{cn}.host"] = cn
            for port in svc.get("ports", []):
                pass2_ctx[f"services.{svc_id}.port"] = str(port)
                pass2_ctx[f"services.{cn}.port"] = str(port)

        # Shared dependencies
        for key, val in user_vars.items():
            if key.startswith("shared.") and val:
                dep_name = key[len("shared."):]
                # Find port from group services
                for other_inst in all_instances:
                    if other_inst.id == inst.id:
                        continue
                    try:
                        other_detail = product_catalog_service.get_by_id(other_inst.catalog_id)
                    except Exception:
                        continue
                    for other_svc in other_detail.recipe.get("services", []):
                        other_cn = f"{other_inst.instance_name}-{other_svc.get('id', '')}"
                        if other_cn == val:
                            ports = other_svc.get("ports", [])
                            pass2_ctx[f"shared.{dep_name}.host"] = val
                            pass2_ctx[f"shared.{dep_name}.url"] = f"{val}:{ports[0]}" if ports else val
                            if ports:
                                pass2_ctx[f"shared.{dep_name}.port"] = str(ports[0])

        def _resolve(text: str, ctx: dict[str, str]) -> str:
            def _repl(m: re.Match) -> str:
                key = m.group(1).strip()
                return ctx.get(key, m.group(0))
            return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", _repl, text)

        def resolve(text: str) -> str:
            return _resolve(_resolve(text, pass1_ctx), pass2_ctx)

        def resolve_env_value(text: str) -> str:
            """Resolve {{ }} and extract ${} into .env."""
            resolved = resolve(text)
            # Extract ${VAR} and resolve from generated secrets, vault, or leave empty
            def _env_repl(m: re.Match) -> str:
                ref = m.group(1)
                # Priority: user secrets > generated secrets > platform vault
                if ref in u_secrets:
                    env_vars[ref] = u_secrets[ref]
                elif ref in gen_secrets:
                    env_vars[ref] = gen_secrets[ref]
                elif ref in vault:
                    env_vars[ref] = vault[ref]
                else:
                    env_vars[ref] = ""  # placeholder
                return f"${{{ref}}}"
            return re.sub(r"\$\{([^}]+)\}", _env_repl, resolved)

        # Generate services
        for svc in recipe.get("services", []):
            svc_id = svc.get("id", "")
            container_name = resolve(f"{inst_name}-{svc_id}")

            env = {}
            for k, v in svc.get("env_template", {}).items():
                env[k] = resolve_env_value(str(v))

            svc_out: dict[str, Any] = {
                "image": svc.get("image", ""),
                "container_name": container_name,
                "restart": "unless-stopped",
            }
            if svc.get("ports"):
                svc_out["ports"] = [f"{p}:{p}" for p in svc["ports"]]
            if env:
                svc_out["environment"] = env
            if svc.get("volumes"):
                svc_out["volumes"] = [
                    f"{container_name}-{vol['name']}:{vol['mount']}"
                    for vol in svc["volumes"]
                ]
            if svc.get("requires_services"):
                svc_out["depends_on"] = [
                    f"{inst_name}-{dep}" for dep in svc["requires_services"]
                ]

            svc_out["networks"] = ["agflow"]
            compose_services[container_name] = svc_out

    # Build compose dict
    compose_dict: dict[str, Any] = {
        "services": compose_services,
        "networks": {"agflow": {"driver": "bridge"}},
    }

    # Collect volumes
    all_volumes = set()
    for svc in compose_services.values():
        for v in svc.get("volumes", []):
            vol_name = v.split(":")[0]
            all_volumes.add(vol_name)
    if all_volumes:
        compose_dict["volumes"] = {v: None for v in sorted(all_volumes)}

    compose_yaml = yaml.dump(compose_dict, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Build .env
    env_lines = []
    for k in sorted(env_vars.keys()):
        v = env_vars[k]
        env_lines.append(f"{k}={v}")
    env_content = "\n".join(env_lines)

    # Store in DB
    unique_nullable = sorted(set(nullable_secrets))
    await execute(
        """
        UPDATE project_deployments
        SET generated_compose = $1, generated_env = $2, generated_secrets = $3::jsonb,
            nullable_secrets = $4::jsonb, status = 'generated'
        WHERE id = $5
        """,
        compose_yaml, env_content, json.dumps(gen_secrets), json.dumps(unique_nullable), deployment_id,
    )

    _log.info("deployments.generated", id=str(deployment_id), services=len(compose_services))
    return await get_by_id(deployment_id)
