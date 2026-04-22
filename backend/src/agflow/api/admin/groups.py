from __future__ import annotations

import re
from uuid import UUID

import yaml
from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.products import GroupCreate, GroupSummary, GroupUpdate
from agflow.services import groups_service, product_instances_service, product_catalog_service

router = APIRouter(
    prefix="/api/admin/groups",
    tags=["admin-groups"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[GroupSummary])
async def list_groups(project_id: UUID):
    return await groups_service.list_by_project(project_id)


@router.post("", response_model=GroupSummary, status_code=status.HTTP_201_CREATED)
async def create_group(payload: GroupCreate):
    return await groups_service.create(
        project_id=payload.project_id,
        name=payload.name,
        max_agents=payload.max_agents,
    )


@router.get("/{group_id}", response_model=GroupSummary)
async def get_group(group_id: UUID):
    try:
        return await groups_service.get_by_id(group_id)
    except groups_service.GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{group_id}", response_model=GroupSummary)
async def update_group(group_id: UUID, payload: GroupUpdate):
    try:
        return await groups_service.update(group_id, **payload.model_dump(exclude_unset=True))
    except groups_service.GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{group_id}/available-services")
async def available_services(group_id: UUID):
    """List all Docker services from all instances in this group."""
    instances = await product_instances_service.list_by_group(group_id)
    services = []
    for inst in instances:
        try:
            detail = product_catalog_service.get_by_id(inst.catalog_id)
        except Exception:
            continue
        for svc in detail.recipe.get("services", []):
            svc_id = svc.get("id", "")
            container_name = f"{inst.instance_name}-{svc_id}"
            ports = svc.get("ports", [])
            services.append({
                "instance_id": str(inst.id),
                "instance_name": inst.instance_name,
                "catalog_id": inst.catalog_id,
                "service_id": svc_id,
                "container_name": container_name,
                "image": svc.get("image", ""),
                "ports": ports,
            })
    return {"services": services}


@router.get("/{group_id}/preview")
async def preview_group(group_id: UUID):
    """Generate a YAML preview of the group with variables resolved."""
    try:
        group = await groups_service.get_by_id(group_id)
    except groups_service.GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    instances = await product_instances_service.list_by_group(group_id)

    # Build the full secret reference set
    all_secret_refs: set[str] = set()
    resolved_secrets: set[str] = set()

    # 1. Secrets with generate methods → will be auto-generated
    generatable: set[str] = set()
    for inst in instances:
        try:
            detail = product_catalog_service.get_by_id(inst.catalog_id)
        except Exception:
            continue
        for s in detail.recipe.get("secrets_required", []):
            method = s.get("generate")
            if method and method != "null":
                generatable.add(s.get("name", ""))

    # 2. Platform secrets (table secrets)
    platform_keys: set[str] = set()
    try:
        from agflow.services import secrets_service
        platform_keys = {s.var_name for s in await secrets_service.list_all()}
    except Exception:
        pass

    # 3. User secrets (table user_secrets) — highest priority
    user_secret_keys: set[str] = set()
    try:
        from agflow.db.pool import fetch_all as _fetch_all
        user_rows = await _fetch_all("SELECT name FROM user_secrets")
        user_secret_keys = {r["name"] for r in user_rows}
    except Exception:
        pass

    # Combined: anything in these sets is considered resolvable
    all_resolvable = generatable | platform_keys | user_secret_keys

    output_services: list[dict] = []

    for inst in instances:
        try:
            detail = product_catalog_service.get_by_id(inst.catalog_id)
        except Exception:
            continue

        recipe = detail.recipe
        user_vars = inst.variables or {}

        # Build resolution context
        inst_name = inst.instance_name

        # Pass 1 context: {{_name}} → instance name
        pass1_ctx: dict[str, str] = {"_name": inst_name}

        # Pass 2 context: user vars + computed service hosts
        pass2_ctx: dict[str, str] = {}
        pass2_ctx.update(user_vars)
        pass2_ctx["instance_name"] = inst_name
        pass2_ctx["instance_id"] = str(inst.id)
        pass2_ctx["_name"] = inst_name

        # Compute service hosts after pass1 (service names use instance_name)
        for svc in recipe.get("services", []):
            svc_id = svc.get("id", "")
            container_name = f"{inst_name}-{svc_id}"
            pass2_ctx[f"services.{container_name}.host"] = container_name
            pass2_ctx[f"services.{svc_id}.host"] = container_name
            for port in svc.get("ports", []):
                pass2_ctx[f"services.{container_name}.port"] = str(port)
                pass2_ctx[f"services.{svc_id}.port"] = str(port)

        # Resolve shared.X.Y from user_vars["shared.X"] → container name
        # Build a lookup of all services in the group for port resolution
        all_group_services: dict[str, dict] = {}
        for other_inst in instances:
            try:
                other_detail = product_catalog_service.get_by_id(other_inst.catalog_id)
            except Exception:
                continue
            for other_svc in other_detail.recipe.get("services", []):
                cn = f"{other_inst.instance_name}-{other_svc.get('id', '')}"
                all_group_services[cn] = {
                    "host": cn,
                    "ports": other_svc.get("ports", []),
                }

        for key, val in user_vars.items():
            if key.startswith("shared.") and val:
                dep_name = key[len("shared."):]  # e.g. "pgvector"
                selected_container = val
                svc_info = all_group_services.get(selected_container, {})
                host = svc_info.get("host", selected_container)
                ports = svc_info.get("ports", [])
                port = str(ports[0]) if ports else ""
                pass2_ctx[f"shared.{dep_name}.host"] = host
                pass2_ctx[f"shared.{dep_name}.url"] = f"{host}:{port}" if port else host
                if port:
                    pass2_ctx[f"shared.{dep_name}.port"] = port

        def _resolve(text: str, ctx: dict[str, str]) -> str:
            """Replace {{ var }} with resolved values from ctx."""
            def _repl(m: re.Match) -> str:
                key = m.group(1).strip()
                if key in ctx:
                    return ctx[key]
                return m.group(0)
            return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", _repl, text)

        def resolve_jinja(text: str) -> str:
            """Two-pass resolution: first {{_name}}, then everything else."""
            after_pass1 = _resolve(text, pass1_ctx)
            return _resolve(after_pass1, pass2_ctx)

        for svc in recipe.get("services", []):
            svc_id = svc.get("id", "")
            container_name = f"{inst.instance_name}-{svc_id}"
            env = {}
            for k, v in svc.get("env_template", {}).items():
                resolved = resolve_jinja(str(v))
                env[k] = resolved
                # Track secret refs
                for m in re.finditer(r"\$\{([^}]+)\}", resolved):
                    ref = m.group(1)
                    all_secret_refs.add(ref)
                    if ref in all_resolvable:
                        resolved_secrets.add(ref)

            svc_out: dict = {
                "container_name": container_name,
                "image": svc.get("image", ""),
            }
            if svc.get("ports"):
                svc_out["ports"] = svc["ports"]
            if env:
                svc_out["environment"] = env
            if svc.get("volumes"):
                svc_out["volumes"] = [
                    f"{container_name}-{vol['name']}:{vol['mount']}"
                    for vol in svc["volumes"]
                ]
            if svc.get("healthcheck"):
                svc_out["healthcheck"] = svc["healthcheck"]

            output_services.append(svc_out)

    compose_dict = {
        "services": {svc["container_name"]: {k: v for k, v in svc.items() if k != "container_name"} for svc in output_services},
    }

    preview_yaml = yaml.dump(compose_dict, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return {
        "yaml": preview_yaml,
        "secret_refs": sorted(all_secret_refs),
        "resolved_secrets": sorted(resolved_secrets),
        "unresolved_secrets": sorted(all_secret_refs - resolved_secrets),
    }


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: UUID):
    try:
        await groups_service.delete(group_id)
    except groups_service.GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
