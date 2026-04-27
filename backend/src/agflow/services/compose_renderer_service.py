"""Build the enriched deployment data structure for a project.

Given a project_id, we walk every group + instance and produce a plain Python
structure that embeds the product recipe's ``services`` block with all
``{{ placeholders }}`` resolved from instance variables + cross-service hosts,
plus ``agflow.*`` labels and the project's Docker network injected onto each
service. ``${VAR}`` references are kept as literals — they live in the ``.env``
at deploy time.

This structure is displayed verbatim in the "Deploy" dialog for validation. The
actual docker-compose.yml construction is deferred to a later phase.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

import structlog
import yaml
from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from agflow.db.pool import fetch_all, fetch_one
from agflow.services import (
    groups_service,
    product_catalog_service,
    product_instances_service,
    projects_service,
    template_files_service,
)

_JINJA_ENV = SandboxedEnvironment(
    undefined=StrictUndefined,
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=True,
)

_log = structlog.get_logger(__name__)


class ComposeRenderError(Exception):
    pass


def _group_slug(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", (name or "").upper())


def _resolve_template(text: str, *contexts: dict[str, str]) -> str:
    """Replace ``{{ key }}`` placeholders using the supplied contexts in order."""
    def repl(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        for ctx in contexts:
            if key in ctx:
                return str(ctx[key])
        return m.group(0)
    return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", repl, text or "")


def _build_instance_ctx(
    instance: Any,
    recipe: dict[str, Any],
    all_instances: list[Any],
    recipes_by_id: dict[str, dict[str, Any]],
) -> dict[str, str]:
    """Build the resolution context (used for ``{{ ... }}`` placeholders)."""
    ctx: dict[str, str] = {}
    user_vars = instance.variables or {}
    for k, v in user_vars.items():
        if v is not None:
            ctx[k] = str(v)
    ctx["instance_name"] = instance.instance_name
    ctx["instance_id"] = str(instance.id)
    ctx["_name"] = instance.instance_name

    # Service hosts (same-instance lookups: services.<id>.host / port)
    for svc in recipe.get("services", []):
        svc_id = svc.get("id", "")
        cn = f"{instance.instance_name}-{svc_id}"
        ctx[f"services.{svc_id}.host"] = cn
        ctx[f"services.{cn}.host"] = cn
        ports = svc.get("ports", [])
        if ports:
            ctx[f"services.{svc_id}.port"] = str(ports[0])
            ctx[f"services.{cn}.port"] = str(ports[0])

    # Shared deps resolved against *other* instances' services
    for key, val in user_vars.items():
        if not key.startswith("shared.") or not val:
            continue
        dep_name = key[len("shared."):]
        for other in all_instances:
            if other.id == instance.id:
                continue
            other_recipe = recipes_by_id.get(str(other.catalog_id))
            if not other_recipe:
                continue
            for other_svc in other_recipe.get("services", []):
                other_cn = f"{other.instance_name}-{other_svc.get('id', '')}"
                if other_cn != val:
                    continue
                ports = other_svc.get("ports", [])
                ctx[f"shared.{dep_name}.host"] = other_cn
                ctx[f"shared.{dep_name}.url"] = f"{other_cn}:{ports[0]}" if ports else other_cn
                if ports:
                    ctx[f"shared.{dep_name}.port"] = str(ports[0])

    return ctx


def _build_group_context(
    group: Any,
    instances: list[Any],
    all_instances: list[Any],
    recipes_by_id: dict[str, dict[str, Any]],
    network: str,
) -> dict[str, Any]:
    """Build the enriched services data for one group (pre-rendered, no templating).

    Each service is decorated with the agflow labels + the project's Docker network.
    ``${VAR}`` references are kept as literals — they will be resolved from the .env
    at compose-up time.
    """
    group_slug = _group_slug(group.name)

    # Stable ordering for instance_seq: by created_at if available, else by name.
    sorted_instances = sorted(
        instances,
        key=lambda i: (getattr(i, "created_at", None) or "", getattr(i, "instance_name", "") or ""),
    )
    instance_seq_by_id: dict[Any, int] = {
        inst.id: idx for idx, inst in enumerate(sorted_instances, start=1)
    }

    rendered_instances: list[dict[str, Any]] = []
    for inst in instances:
        recipe = recipes_by_id.get(str(inst.catalog_id))
        if not recipe:
            continue

        resolution_ctx = _build_instance_ctx(inst, recipe, all_instances, recipes_by_id)
        services: list[dict[str, Any]] = []

        runtime_id = str(inst.group_id)
        runtime_seq = str(instance_seq_by_id.get(inst.id, 1))

        for svc in recipe.get("services", []):
            # Optional services are skipped unless explicitly enabled via the
            # instance variable ``enable_<svc_id>`` (e.g. enable_rag-worker=true).
            if svc.get("optional"):
                flag = (inst.variables or {}).get(f"enable_{svc.get('id', '')}")
                if str(flag).lower() not in ("1", "true", "yes", "on"):
                    continue
            svc_id = svc.get("id", "")
            container = f"{inst.instance_name}-{svc_id}"

            env: dict[str, str] = {}
            for k, v in (svc.get("env_template") or {}).items():
                env[k] = _resolve_template(str(v), resolution_ctx)

            labels = [
                f"agflow.group_id={inst.group_id}",
                f"agflow.instance_id={inst.id}",
                f"agflow.runtime_id={runtime_id}",
                f"agflow.runtime_seq={runtime_seq}",
            ]

            services.append({
                "id": svc_id,
                "container_name": container,
                "image": svc.get("image", ""),
                "restart": "unless-stopped",
                "ports": list(svc.get("ports") or []),
                "environment": env,
                "volumes": [
                    {
                        "name": vol.get("name", ""),
                        "mount": vol.get("mount", ""),
                        "docker_volume": f"{container}-{vol.get('name', '')}" if vol.get("name") else "",
                    }
                    for vol in (svc.get("volumes") or [])
                ],
                "depends_on": [
                    f"{inst.instance_name}-{dep}"
                    for dep in (svc.get("requires_services") or [])
                ],
                "labels": labels,
                "networks": [network],
            })

        rendered_instances.append({
            "id": str(inst.id),
            "group_id": str(inst.group_id),
            "instance_name": inst.instance_name,
            "catalog_id": str(inst.catalog_id),
            "services": services,
        })

    volume_names: set[str] = set()
    for inst in rendered_instances:
        for svc in inst["services"]:
            for vol in svc["volumes"]:
                dv = vol.get("docker_volume")
                if dv:
                    volume_names.add(dv)

    return {
        "group": {
            "id": str(group.id),
            "name": group.name,
            "slug": group_slug,
        },
        "group_slug": group_slug,
        "network": network,
        "instances": rendered_instances,
        "volumes": sorted(volume_names),
    }


async def build_deployment_data(project_id: UUID) -> tuple[dict[str, Any], list[str]]:
    """Build the deployment data structure for a project.

    Returns ``(data, env_refs)`` where ``data`` is a dict keyed by group, each
    containing fully-resolved ``services`` blocks, and ``env_refs`` is the
    ordered list of unique ``${VAR}`` references found anywhere in the data.
    """
    project = await projects_service.get_by_id(project_id)
    network = project.network or "agflow"
    groups = await groups_service.list_by_project(project_id)

    all_instances: list[Any] = []
    for g in groups:
        all_instances.extend(await product_instances_service.list_by_group(g.id))

    recipes_by_id: dict[str, dict[str, Any]] = {}
    for inst in all_instances:
        key = str(inst.catalog_id)
        if key in recipes_by_id:
            continue
        try:
            detail = product_catalog_service.get_by_id(inst.catalog_id)
        except Exception:
            continue
        recipes_by_id[key] = detail.recipe

    group_blocks: list[dict[str, Any]] = []
    for g in groups:
        group_instances = [i for i in all_instances if i.group_id == g.id]
        if not group_instances:
            continue
        block = _build_group_context(g, group_instances, all_instances, recipes_by_id, network)
        group_blocks.append(block)

    data: dict[str, Any] = {
        "project": {
            "id": str(project.id),
            "name": project.display_name,
            "network": network,
        },
        "groups": group_blocks,
    }

    env_refs = _extract_env_refs_from(data)
    return data, env_refs


_ENV_REF_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _extract_env_refs_from(value: Any, seen: dict[str, None] | None = None) -> list[str]:
    """Walk a nested dict/list/str structure and collect unique ${VAR} refs."""
    if seen is None:
        seen = {}
    if isinstance(value, str):
        for match in _ENV_REF_RE.finditer(value):
            seen.setdefault(match.group(1), None)
    elif isinstance(value, dict):
        for v in value.values():
            _extract_env_refs_from(v, seen)
    elif isinstance(value, list):
        for v in value:
            _extract_env_refs_from(v, seen)
    return list(seen.keys())


async def render_group_compose(
    deployment_data: dict[str, Any],
    group_id: UUID,
) -> str:
    """Render the docker-compose YAML for a single group using its Jinja template.

    The group must have ``compose_template_slug`` set and the referenced template
    must contain at least one ``*.sh.j2`` file. The Jinja context is the group's
    block from ``deployment_data`` (keys: group, group_slug, network, instances,
    volumes).
    """
    groups = deployment_data.get("groups", []) if isinstance(deployment_data, dict) else []
    block = next((g for g in groups if g.get("group", {}).get("id") == str(group_id)), None)
    if block is None:
        raise ComposeRenderError(
            f"Group {group_id} has no data in this deployment (was it regenerated?)"
        )

    try:
        group = await groups_service.get_by_id(group_id)
    except groups_service.GroupNotFoundError as exc:
        raise ComposeRenderError(str(exc)) from exc

    slug = group.compose_template_slug
    if not slug:
        raise ComposeRenderError(
            f"Group {group.name!r} has no compose_template_slug — associate a "
            f"template via the group editor."
        )

    files = template_files_service.list_files(slug)
    sh_files = [f["filename"] for f in files if f["filename"].endswith(".sh.j2")]
    if not sh_files:
        raise ComposeRenderError(
            f"Template {slug!r} has no *.sh.j2 file — create one in "
            f"/templates/{slug} (kind=sh)."
        )
    filename = sh_files[0]

    try:
        content = template_files_service.read_file(slug, filename)
    except FileNotFoundError as exc:
        raise ComposeRenderError(str(exc)) from exc

    try:
        template = _JINJA_ENV.from_string(content or "")
        return template.render(**block)
    except TemplateError as exc:
        raise ComposeRenderError(
            f"Jinja2 rendering failed for template {slug!r}/{filename!r}: {exc}"
        ) from exc


# ── SaaS runtime renderer (multi-replica + shared user network) ───────────────


async def render_for_runtime(
    runtime_id: UUID,
    *,
    user_network: str,
) -> tuple[str, list[str]]:
    """Render the docker-compose YAML for a SaaS runtime.

    Behaviour vs the legacy admin/template-based rendering:
      - Skips groups not selected (no row in project_group_runtimes).
      - For each selected group with replica_count = N, emits N copies of every
        service of every instance in the group (suffix ``_{i}`` for i in 0..N-1).
      - Container/service hostnames are prefixed with the runtime short id
        (``rt_{rt8}_{service}_{i}``) so multiple runtimes of the same user can
        coexist on the user's shared Docker network without DNS collision.
      - No ``ports:`` host mapping — Docker assigns ephemeral host ports;
        the runtime endpoint API discovers them via ``docker ps``.
      - ``networks`` block declares ``default`` as ``external: true`` with name
        ``user_network`` so all the user's runtimes share one bridge.
      - ``${VAR}`` references in env values are kept as literals; the route
        handler merges them with user_secrets + auto-generated platform
        secrets to produce the .env file pushed alongside the compose.

    Returns ``(compose_yaml, env_var_names)``.
    """
    rt_short = runtime_id.hex[:8]

    # Load runtime + group_runtimes (with replica_count). We don't need the
    # full ProjectRuntimeRow — just the (group_id, replica_count) mapping.
    rows = await fetch_all(
        """
        SELECT gr.group_id, gr.replica_count, g.name AS group_name
        FROM project_group_runtimes gr
        JOIN groups g ON g.id = gr.group_id
        WHERE gr.project_runtime_id = $1 AND gr.deleted_at IS NULL
          AND gr.replica_count > 0
        ORDER BY g.name
        """,
        runtime_id,
    )
    if not rows:
        raise ComposeRenderError(
            f"Runtime {runtime_id} has no selected groups (replica_count = 0 for all).",
        )

    # Resolve project_id from the runtime row.
    rt_row = await fetch_one(
        "SELECT project_id FROM project_runtimes WHERE id = $1 AND deleted_at IS NULL",
        runtime_id,
    )
    if rt_row is None:
        raise ComposeRenderError(f"Runtime {runtime_id} not found")
    project_id = rt_row["project_id"]

    services_dict: dict[str, dict[str, Any]] = {}
    volume_names: set[str] = set()

    for row in rows:
        group_id = row["group_id"]
        replica_count = row["replica_count"]
        instances = await product_instances_service.list_by_group(group_id)
        if not instances:
            continue

        # Load all recipes for the group's instances once.
        recipes_by_id: dict[str, dict[str, Any]] = {}
        for inst in instances:
            key = str(inst.catalog_id)
            if key in recipes_by_id:
                continue
            try:
                detail = product_catalog_service.get_by_id(inst.catalog_id)
            except Exception:
                continue
            recipes_by_id[key] = detail.recipe

        for inst in instances:
            recipe = recipes_by_id.get(str(inst.catalog_id))
            if not recipe:
                continue

            for replica_index in range(replica_count):
                # Each replica gets its own resolution context so that
                # cross-service references within the same replica resolve
                # to the prefixed hostname.
                ctx = _build_runtime_instance_ctx(
                    inst=inst,
                    recipe=recipe,
                    replica_index=replica_index,
                    rt_short=rt_short,
                )

                for svc in recipe.get("services", []):
                    if svc.get("optional"):
                        flag = (inst.variables or {}).get(f"enable_{svc.get('id', '')}")
                        if str(flag).lower() not in ("1", "true", "yes", "on"):
                            continue

                    svc_id = svc.get("id", "")
                    suffix = f"_{replica_index}" if replica_count > 1 else ""
                    hostname = f"rt_{rt_short}_{svc_id}{suffix}"
                    container_name = f"agflow-rt-{rt_short}-{svc_id}{suffix}"

                    env: dict[str, str] = {}
                    for k, v in (svc.get("env_template") or {}).items():
                        env[k] = _resolve_template(str(v), ctx)

                    labels = [
                        f"agflow.runtime_id={runtime_id}",
                        f"agflow.group_id={group_id}",
                        f"agflow.instance_id={inst.id}",
                        f"agflow.service_id={svc_id}",
                        f"agflow.replica_index={replica_index}",
                    ]

                    svc_entry: dict[str, Any] = {
                        "image": svc.get("image", ""),
                        "container_name": container_name,
                        "hostname": hostname,
                        "restart": "unless-stopped",
                        "labels": labels,
                        "networks": ["default"],
                    }

                    # Expose container ports without host bind → Docker assigns
                    # random ephemeral host ports. The /endpoints API discovers
                    # them via `docker ps`.
                    container_ports = svc.get("ports") or []
                    if container_ports:
                        svc_entry["expose"] = [str(p) for p in container_ports]

                    if env:
                        svc_entry["environment"] = env

                    if svc.get("volumes"):
                        vols = []
                        for vol in svc["volumes"]:
                            name = vol.get("name", "")
                            mount = vol.get("mount", "")
                            if not name or not mount:
                                continue
                            docker_vol = f"{container_name}-{name}"
                            volume_names.add(docker_vol)
                            vols.append(f"{docker_vol}:{mount}")
                        if vols:
                            svc_entry["volumes"] = vols

                    if svc.get("requires_services"):
                        svc_entry["depends_on"] = [
                            f"rt_{rt_short}_{dep}{suffix}"
                            for dep in svc["requires_services"]
                        ]

                    if svc.get("healthcheck"):
                        svc_entry["healthcheck"] = svc["healthcheck"]

                    services_dict[hostname] = svc_entry

    if not services_dict:
        raise ComposeRenderError(
            f"Runtime {runtime_id}: no services rendered "
            f"(missing recipes or all services optional + disabled).",
        )

    compose_dict: dict[str, Any] = {
        "services": services_dict,
        "networks": {
            "default": {"name": user_network, "external": True},
        },
    }
    if volume_names:
        compose_dict["volumes"] = {name: {} for name in sorted(volume_names)}

    compose_yaml = yaml.dump(
        compose_dict, default_flow_style=False, allow_unicode=True, sort_keys=False,
    )

    env_var_names = _extract_env_refs_from(compose_dict)

    _log.info(
        "compose_renderer.render_for_runtime",
        runtime_id=str(runtime_id),
        project_id=str(project_id),
        service_count=len(services_dict),
        env_var_count=len(env_var_names),
    )

    return compose_yaml, env_var_names


def _build_runtime_instance_ctx(
    *,
    inst: Any,
    recipe: dict[str, Any],
    replica_index: int,
    rt_short: str,
) -> dict[str, str]:
    """Build the Jinja resolution context for a runtime replica.

    Differs from `_build_instance_ctx` by emitting prefixed hostnames so that
    cross-service references (``{{ services.X.host }}``) resolve to the
    runtime's own hostname space instead of the design-time
    ``{instance_name}-{svc_id}`` convention.
    """
    ctx: dict[str, str] = {}
    user_vars = inst.variables or {}
    for k, v in user_vars.items():
        if v is not None:
            ctx[k] = str(v)
    ctx["instance_name"] = inst.instance_name
    ctx["instance_id"] = str(inst.id)
    ctx["_name"] = inst.instance_name
    ctx["replica_index"] = str(replica_index)

    suffix = f"_{replica_index}"
    for svc in recipe.get("services", []):
        svc_id = svc.get("id", "")
        # Default same-replica reference. For replica_count = 1, the renderer
        # omits the suffix on hostnames; we still resolve to that bare name
        # via the no-suffix entry.
        prefixed_with_idx = f"rt_{rt_short}_{svc_id}{suffix}"
        prefixed_no_idx = f"rt_{rt_short}_{svc_id}"
        # Both lookup forms point to the same-replica hostname so that recipes
        # which don't know about replicas keep working.
        ctx[f"services.{svc_id}.host"] = prefixed_with_idx
        ctx[f"services.{svc_id}.host_unindexed"] = prefixed_no_idx
        ports = svc.get("ports", [])
        if ports:
            ctx[f"services.{svc_id}.port"] = str(ports[0])

    return ctx
