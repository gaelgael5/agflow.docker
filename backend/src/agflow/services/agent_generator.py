from __future__ import annotations

import json
import os
import re
from typing import Any
from uuid import UUID

import httpx
import structlog

from agflow.services import (
    agent_files_service,
    agent_profiles_service,
    agents_service,
    dockerfile_files_service,
    mcp_catalog_service,
    role_documents_service,
    role_sections_service,
    roles_service,
)
from agflow.services.container_runner import resolve_templates

_log = structlog.get_logger(__name__)

_MACRO_RE = re.compile(r"\[!(\w+)\(([^)]*)\)\]")


async def _expand_macros(text: str) -> str:
    """Expand [!function(argument)] macros in markdown text."""
    result = text
    for match in _MACRO_RE.finditer(text):
        func_name = match.group(1)
        argument = match.group(2).strip()
        try:
            if func_name == "openapi":
                replacement = await _macro_openapi(argument)
            else:
                replacement = f"<!-- unknown macro: {func_name} -->"
            result = result.replace(match.group(0), replacement)
        except Exception as exc:
            _log.warning("macro.error", func=func_name, arg=argument, error=str(exc))
            result = result.replace(match.group(0), f"<!-- macro error: {exc} -->")
    return result


async def _macro_openapi(url: str) -> str:
    """Fetch an OpenAPI spec and render it as markdown endpoint list."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(url)
        res.raise_for_status()
        spec = res.json()

    paths = spec.get("paths", {})
    groups: dict[str, list[str]] = {}

    for path, methods in sorted(paths.items()):
        for method, detail in methods.items():
            if method in ("parameters", "servers", "summary", "description"):
                continue
            method_upper = method.upper()
            tags = detail.get("tags", ["Other"])
            summary = detail.get("summary", "")
            line = f"- `{method_upper} {path}` : {summary}"
            for tag in tags:
                groups.setdefault(tag, []).append(line)

    parts: list[str] = []
    for tag, lines in groups.items():
        parts.append(f"### {tag}")
        parts.extend(lines)
        parts.append("")

    return "\n".join(parts)


def _apply_overrides(
    params_json: str,
    env_overrides: dict[str, Any],
    mount_overrides: dict[str, Any],
    param_overrides: dict[str, Any],
) -> str:
    """Apply agent overrides to a Dockerfile.json content string."""
    try:
        parsed = json.loads(params_json)
    except (json.JSONDecodeError, TypeError):
        return params_json

    docker = parsed.get("docker", {})

    # Apply env overrides
    envs = docker.get("Environments", {})
    for k, override in env_overrides.items():
        if override.get("excluded"):
            envs.pop(k, None)
        elif "value" in override:
            envs[k] = override["value"]
    docker["Environments"] = envs

    # Apply mount overrides
    mounts = docker.get("Mounts", [])
    new_mounts = []
    for m in mounts:
        target = m.get("target", "")
        override = mount_overrides.get(target, {})
        if override.get("excluded"):
            continue
        if "source" in override:
            m = {**m, "source": override["source"]}
        new_mounts.append(m)
    docker["Mounts"] = new_mounts

    parsed["docker"] = docker

    # Apply param overrides
    params = parsed.get("Params", {})
    for k, override in param_overrides.items():
        if override.get("excluded"):
            params.pop(k, None)
        elif "value" in override:
            params[k] = override["value"]
    parsed["Params"] = params

    return json.dumps(parsed)


def _data_dir() -> str:
    return os.environ.get("AGFLOW_DATA_DIR", "/app/data")


def _agents_dir() -> str:
    return os.path.join(_data_dir(), "agents")


async def generate(
    agent_id: UUID,
    profile_id: UUID | None = None,
    user_secrets: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Generate the full agent workspace on disk.

    Creates {AGFLOW_DATA_DIR}/agents/{slug}/ with:
      - run.sh          — docker run command
      - prompt.md       — identity + profile documents
      - mcp.json        — MCP server configs
      - .env            — resolved environment variables
      - skills/         — skill files
    """
    agent = await agents_service.get_by_id(agent_id)
    slug = agent.slug

    generated_dir = os.path.join(_agents_dir(), slug, "generated")
    os.makedirs(generated_dir, exist_ok=True)

    # Load generation config (paths, ref_prefix) from Dockerfile.json
    gen_config = dockerfile_files_service.read_generation_config(agent.dockerfile_id)
    gen_paths = gen_config["paths"]
    ref_prefix = gen_config["prompt_ref_prefix"]

    # out_dir = generated/ (root for .env, prompt.md, run.sh, mcp.json)
    out_dir = generated_dir
    os.makedirs(out_dir, exist_ok=True)

    role = await roles_service.get_by_id(agent.role_id)
    await role_sections_service.list_for_role(agent.role_id)
    documents = await role_documents_service.list_for_role(agent.role_id)

    # Build prompt.md — via template if configured, else identity only
    tpl_slug = agent.prompt_template_slug if hasattr(agent, "prompt_template_slug") else ""
    tpl_culture = agent.prompt_template_culture if hasattr(agent, "prompt_template_culture") else ""
    if tpl_slug and tpl_culture:
        from jinja2 import Environment as _Env

        tpl_path = os.path.join(
            _data_dir(), "templates", tpl_slug, f"{tpl_culture}.md.j2"
        )
        if os.path.isfile(tpl_path):
            with open(tpl_path, encoding="utf-8") as f:
                tpl_content = f.read()

            # All docs grouped by section for load_section helper
            all_sections: dict[str, list[str]] = {}
            for doc in documents:
                all_sections.setdefault(doc.section, []).append(doc.content_md)

            def _make_loader(sects: dict[str, list[str]]):
                def load_section(name: str) -> list[str]:
                    return sects.get(name, [])
                return load_section

            env = _Env(
                trim_blocks=True,
                lstrip_blocks=True,
                keep_trailing_newline=True,
                autoescape=False,
            )
            _prompt_template = env.from_string(tpl_content)
            _prompt_loader = _make_loader(all_sections)
        else:
            _log.warning("agent_generator.prompt_template_not_found", path=tpl_path)
            _prompt_env = None
            _prompt_template = None
            _prompt_loader = None
    else:
        _prompt_env = None
        _prompt_template = None
        _prompt_loader = None

    # Clean old profile files before regeneration
    import shutil

    from jinja2 import Environment

    # Remove old legacy dirs + rebuild from gen_paths
    # Clean output dirs that will be regenerated by profiles
    # Collect all unique output_dir values from profiles, then clean them
    profiles = await agent_profiles_service.list_for_agent(agent_id)
    dirs_to_clean: set[str] = set()
    for profile in profiles:
        pdir = getattr(profile, "output_dir", None) or gen_paths["missions"]
        dirs_to_clean.add(pdir.split("/")[0])  # clean top-level dir (e.g. "workspace")
    for top in dirs_to_clean:
        full = os.path.join(out_dir, top)
        if os.path.isdir(full):
            shutil.rmtree(full)

    # Build per-profile files from profile selections
    for profile in profiles:
        # Skip profiles with no documents selected
        if not profile.document_ids:
            continue

        profile_slug = profile.name.lower().replace(" ", "_")

        # Determine output directory for this profile
        profile_output_dir = os.path.join(
            generated_dir,
            getattr(profile, "output_dir", None) or gen_paths["missions"],
        )
        os.makedirs(profile_output_dir, exist_ok=True)

        # Collect documents selected in this profile, grouped by section
        doc_ids = set(str(d) for d in profile.document_ids)
        sections: dict[str, list[str]] = {}
        for doc in documents:
            if str(doc.id) in doc_ids:
                sections.setdefault(doc.section, []).append(doc.content_md)

        # If profile has a template, render with Jinja2
        tpl_slug = profile.template_slug
        tpl_culture = profile.template_culture
        if tpl_slug and tpl_culture:
            tpl_path = os.path.join(
                _data_dir(), "templates", tpl_slug, f"{tpl_culture}.md.j2"
            )
            if os.path.isfile(tpl_path):
                with open(tpl_path, encoding="utf-8") as f:
                    tpl_content = f.read()

                def _make_load_section(sects: dict[str, list[str]]):
                    def load_section(name: str) -> list[str]:
                        return sects.get(name, [])
                    return load_section

                env = Environment(
                    trim_blocks=True,
                    lstrip_blocks=True,
                    keep_trailing_newline=True,
                    autoescape=False,
                )
                template = env.from_string(tpl_content)
                rendered = template.render(
                    role=role,
                    profile=profile,
                    agent=agent,
                    load_section=_make_load_section(sections),
                )
                if rendered.strip():
                    _write(profile_output_dir, f"{profile_slug}.md", rendered)
                _log.info(
                    "agent_generator.profile_rendered",
                    profile=profile.name,
                    template=f"{tpl_slug}/{tpl_culture}.md.j2",
                )
            else:
                _log.warning(
                    "agent_generator.template_not_found",
                    template=tpl_path,
                )
                # Fallback: concat all sections into {profile_slug}.md
                parts = []
                for contents in sections.values():
                    parts.extend(contents)
                merged = "\n\n---\n\n".join(parts)
                if merged.strip():
                    _write(profile_output_dir, f"{profile_slug}.md", merged)
        else:
            # No template: concat all sections into {profile_slug}.md
            parts = []
            for contents in sections.values():
                parts.extend(contents)
            merged = "\n\n---\n\n".join(parts)
            if merged.strip():
                _write(profile_output_dir, f"{profile_slug}.md", merged)

        _log.info(
            "agent_generator.profile_written",
            profile=profile.name,
            sections=list(sections.keys()),
            doc_count=sum(len(v) for v in sections.values()),
        )

    # Collect generated profiles for the prompt template
    generated_profiles = []
    for profile in profiles:
        if not profile.document_ids:
            continue
        profile_slug = profile.name.lower().replace(" ", "_")
        profile_file = os.path.join(profile_output_dir, f"{profile_slug}.md")
        if os.path.isfile(profile_file):
            generated_profiles.append({
                "name": profile.name,
                "description": profile.description,
                "slug": profile_slug,
                "path": f"{ref_prefix}/{getattr(profile, 'output_dir', None) or gen_paths['missions']}/{profile_slug}.md",
            })

    # ── Contrats API ────────────────────────────────────────
    from agflow.services import api_contracts_service as _ctr_svc
    from agflow.services import openapi_parser as _oapi

    contracts = await _ctr_svc.list_for_agent(str(agent_id))
    contract_context: list[dict[str, Any]] = []

    for contract in contracts:
        contract_output = getattr(contract, "output_dir", None) or gen_paths["contracts"]
        ctr_dir = os.path.join(generated_dir, contract_output, contract.slug)
        # Clean and recreate
        if os.path.isdir(ctr_dir):
            shutil.rmtree(ctr_dir)
        os.makedirs(ctr_dir, exist_ok=True)

        full_detail = await _ctr_svc.get_by_id(contract.id)
        full_tags = _oapi.parse_openapi_tags(full_detail.spec_content)
        overrides = getattr(contract, "tag_overrides", None) or {}

        tag_context: list[dict[str, Any]] = []
        for tag in full_tags:
            resolved_desc = _oapi.resolve_tag_description(tag, overrides)

            # Create tag subdirectory for .sh scripts
            tag_dir = os.path.join(ctr_dir, tag["slug"])
            os.makedirs(tag_dir, exist_ok=True)

            # Generate one .sh per operation
            operation_entries: list[dict[str, Any]] = []
            for op in tag.get("operations", []):
                sh_filename = _oapi.operation_to_filename(op)
                sh_content = _oapi.generate_operation_script(
                    op=op,
                    base_url=contract.base_url,
                    auth_header=contract.auth_header,
                    auth_prefix=contract.auth_prefix,
                    auth_secret_ref=contract.auth_secret_ref or "",
                )
                _write(tag_dir, sh_filename, sh_content)
                os.chmod(os.path.join(tag_dir, sh_filename), 0o755)

                op_name = sh_filename.replace(".sh", "")
                op_desc = _oapi._truncate(
                    op.get("description") or op.get("summary", ""), 200
                )
                operation_entries.append({
                    "name": op_name,
                    "description": op_desc,
                    "path": f"{ref_prefix}/{contract_output}/{contract.slug}/{tag['slug']}/{sh_filename}",
                })

            # Generate .md index for this tag
            md_content = _oapi.generate_tag_index_markdown(
                tag_name=tag["name"],
                tag_description=resolved_desc,
                base_url=contract.base_url,
                auth_header=contract.auth_header,
                auth_prefix=contract.auth_prefix,
                auth_secret_ref=contract.auth_secret_ref or "",
                operations=operation_entries,
            )
            _write(ctr_dir, f"{tag['slug']}.md", md_content)

            tag_context.append({
                "name": tag["name"],
                "slug": tag["slug"],
                "description": resolved_desc,
            })

        contract_context.append({
            "slug": contract.slug,
            "description": contract.description,
            "output_dir": contract_output,
            "tags": tag_context,
        })

    _log.info("agent_generator.contracts_written", count=len(contracts))

    # Render prompt.md — with template or fallback
    if _prompt_template is not None:
        prompt_md = _prompt_template.render(
            role=role,
            agent=agent,
            load_section=_prompt_loader,
            missions=generated_profiles,
            api_contracts=contract_context,
            ref_prefix=ref_prefix,
            paths=gen_paths,
        )
    else:
        prompt_md = f"# {role.display_name}\n\n{role.identity_md}"
        if generated_profiles:
            prompt_md += "\n\n### Missions\n"
            for m in generated_profiles:
                prompt_md += f"\n- {m['description']} : `{m['path']}`"
            prompt_md += "\n"
        if contract_context:
            prompt_md += "\n\n## API disponibles\n"
            for ctr in contract_context:
                prompt_md += f"\n### {ctr['description']}\n"
                for tag in ctr["tags"]:
                    prompt_md += f"\n- {tag['name']} : `{ref_prefix}/{ctr['output_dir']}/{ctr['slug']}/{tag['slug']}.md`"
            prompt_md += "\n"

    prompt_md = await _expand_macros(prompt_md)
    prompt_dir = os.path.dirname(os.path.join(out_dir, gen_paths["prompt"]))
    os.makedirs(prompt_dir, exist_ok=True)
    _write(out_dir, gen_paths["prompt"], prompt_md)

    # Build .env — merge Dockerfile.json Environments with agent overrides
    # Secrets come exclusively from the user's vault — never from platform secrets
    all_secrets = user_secrets or {}

    # Read base env vars + params from Dockerfile.json
    base_env: dict[str, str] = {}
    base_params: dict[str, str] = {}
    files = await dockerfile_files_service.list_for_dockerfile(agent.dockerfile_id)
    params_file = next((f for f in files if f.path == "Dockerfile.json"), None)
    if params_file:
        try:
            parsed = json.loads(params_file.content)
            base_env = parsed.get("docker", {}).get("Environments", {})
            base_params = parsed.get("Params", {})
        except (json.JSONDecodeError, AttributeError):
            pass

    # Read overrides from agent.json
    agent_data = agent_files_service.read_agent(slug)
    env_overrides = agent_data.get("env_overrides", {})
    param_overrides = agent_data.get("param_overrides", {})

    # Build resolved params (apply overrides, then use as template vars)
    resolved_params: dict[str, str] = {}
    for k, v in base_params.items():
        override = param_overrides.get(k, {})
        if override.get("excluded"):
            continue
        resolved_params[k] = str(override.get("value", v))

    _secret_ref_re = re.compile(r"^\$\{(\w+)(?::-([^}]*))?\}$")

    def _resolve_secret(value: str) -> str:
        """Resolve $VAR and ${VAR} and ${VAR:-default} against vault secrets."""
        if not isinstance(value, str):
            return str(value)
        # $VAR (no braces)
        if value.startswith("$") and not value.startswith("${") and len(value) > 1:
            return all_secrets.get(value[1:], "")
        # ${VAR} or ${VAR:-default}
        m = _secret_ref_re.match(value)
        if m:
            return all_secrets.get(m.group(1), m.group(2) or "")
        return value

    env_lines = []
    # Environment variables
    for k, v in base_env.items():
        override = env_overrides.get(k, {})
        if override.get("excluded"):
            continue
        raw = str(override.get("value", v))
        # Step 1: resolve {KEY} agflow templates via Params
        templated = resolve_templates(raw, resolved_params)
        # Step 2: resolve $SECRET / ${SECRET} against vault secrets
        env_lines.append(f"{k}={_resolve_secret(templated)}")
    # Params (exposed as env vars too)
    for k, v in resolved_params.items():
        templated = resolve_templates(str(v), resolved_params)
        env_lines.append(f"{k}={_resolve_secret(templated)}")

    _write(out_dir, gen_paths["env"], "\n".join(env_lines) + "\n")

    # ── MCP installation files ──────────────────────────────────────────
    target = dockerfile_files_service.read_target(agent.dockerfile_id)
    cmd_lines: list[str] = []
    config_blocks: dict[str, list[str]] = {}

    for binding in agent.mcp_bindings:
        mcp = await mcp_catalog_service.get_by_id(binding.mcp_server_id)
        override = (
            binding.parameters_override
            if hasattr(binding, "parameters_override")
            else getattr(binding, "config_overrides", {}) or {}
        )
        runtime = override.get("runtime")
        params = override.get("params", {})

        if not target or not runtime:
            continue

        mode = next(
            (m for m in target.get("modes", []) if m.get("runtime") == runtime),
            None,
        )
        if not mode:
            continue

        template = mode.get("template", "")
        env_entries = {k: _resolve_secret(str(v)) for k, v in params.items() if v}

        env_toml = ""
        if env_entries:
            env_toml = "\n[mcp_servers.env]\n" + "\n".join(
                f'{k} = "{v}"' for k, v in env_entries.items()
            )

        env_json = ""
        if env_entries:
            pairs = ", ".join(f'"{k}": "{v}"' for k, v in env_entries.items())
            env_json = f', "env": {{{pairs}}}'

        resolved = (
            template
            .replace("{name}", mcp.name)
            .replace("{package}", mcp.repo or mcp.name)
            .replace("{env_toml}", env_toml)
            .replace("{env_json}", env_json)
        )

        action_type = mode.get("action_type", "")
        if action_type == "cmd":
            cmd_lines.append(resolved)
        elif action_type == "insert_in_file":
            config_path = mode.get("config_path", "mcp_config")
            config_blocks.setdefault(config_path, []).append(resolved)

    if cmd_lines:
        script = "#!/usr/bin/env bash\nset -euo pipefail\n\n" + "\n".join(cmd_lines) + "\n"
        _write(out_dir, "install_mcp.sh", script)

    for config_path, blocks in config_blocks.items():
        filename = os.path.basename(config_path)
        content = "\n\n".join(blocks) + "\n"
        # Write to generated/{filename} (mount source = filename)
        _write(out_dir, filename, content)
        # Write to {data}/{dockerfile_id}/{filename} for the Docker bind mount
        data_base = os.environ.get("AGFLOW_DATA_DIR", "/app/data")
        mount_path = os.path.join(data_base, agent.dockerfile_id, filename)
        with open(mount_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        _log.info("agent_generator.mcp_config_written", path=mount_path)

    # Also keep mcp.json for backward compat / debug
    mcp_config_legacy = []
    for binding in agent.mcp_bindings:
        override = (
            binding.parameters_override
            if hasattr(binding, "parameters_override")
            else getattr(binding, "config_overrides", {}) or {}
        )
        mcp_config_legacy.append({
            "mcp_server_id": str(binding.mcp_server_id),
            "parameters_override": override,
        })
    _write(out_dir, gen_paths["mcp_json"], json.dumps(mcp_config_legacy, indent=2, ensure_ascii=False))

    # Skills
    skills_dir = os.path.join(out_dir, "skills")
    os.makedirs(skills_dir, exist_ok=True)
    for binding in agent.skill_bindings:
        _write(skills_dir, f"{binding.catalog_skill_id}.md", "")

    # Build run.sh from Dockerfile.json with agent overrides applied
    files = await dockerfile_files_service.list_for_dockerfile(agent.dockerfile_id)
    params_file = next((f for f in files if f.path == "Dockerfile.json"), None)

    run_sh_lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Source resolved secrets",
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        'if [ -f "$SCRIPT_DIR/.env" ]; then',
        '  set -a; source "$SCRIPT_DIR/.env"; set +a',
        "fi",
        "",
    ]
    if params_file:
        import secrets as _secrets
        instance_id = _secrets.token_hex(3)

        patched_content = _apply_overrides(params_file.content, env_overrides,
            agent_data.get("mount_overrides", {}),
            agent_data.get("param_overrides", {}))

        try:
            patched = json.loads(patched_content)
        except (json.JSONDecodeError, TypeError):
            patched = {}

        docker_cfg = patched.get("docker", {})
        container = docker_cfg.get("Container", {})
        runtime = docker_cfg.get("Runtime", {})
        resources = docker_cfg.get("Resources", {})
        network = docker_cfg.get("Network", {})
        environments = docker_cfg.get("Environments", {})
        mounts = docker_cfg.get("Mounts", [])

        image = container.get("Image", f"agflow-{agent.dockerfile_id}:latest")
        name = container.get("Name", f"agent-{slug}-{instance_id}")

        cmd_parts = ["docker run"]
        cmd_parts.append(f"--name {name}")
        net_mode = network.get("Mode", "bridge")
        if net_mode:
            cmd_parts.append(f"--network {net_mode}")
        if runtime.get("Init"):
            cmd_parts.append("--init")
        stop_signal = runtime.get("StopSignal")
        if stop_signal:
            cmd_parts.append(f"--stop-signal {stop_signal}")
        stop_timeout = runtime.get("StopTimeout")
        if stop_timeout:
            cmd_parts.append(f"--stop-timeout {stop_timeout}")
        workdir = runtime.get("WorkingDir")
        if workdir:
            cmd_parts.append(f"-w {workdir}")
        mem = resources.get("Memory")
        if mem:
            cmd_parts.append(f"--memory {mem}")
        cpus = resources.get("Cpus")
        if cpus:
            cmd_parts.append(f"--cpus {cpus}")
        for k, v in environments.items():
            cmd_parts.append(f'-e "{k}={v}"')
        for m in mounts:
            src = m.get("source", "")
            tgt = m.get("target", "")
            ro = ":ro" if m.get("readonly") else ""
            cmd_parts.append(f'-v "{src}:{tgt}{ro}"')
        cmd_parts.append(image)

        run_sh_lines.append(" \\\n  ".join(cmd_parts))
    else:
        run_sh_lines.append("# No Dockerfile.json found")
        run_sh_lines.append(f"docker run agflow-{agent.dockerfile_id}:latest")

    _write(out_dir, gen_paths["run"], "\n".join(run_sh_lines) + "\n")
    os.chmod(os.path.join(out_dir, gen_paths["run"]), 0o755)

    _log.info("agent.generate", slug=slug, dir=out_dir)

    return {
        "slug": slug,
        "path": out_dir,
        "files": os.listdir(out_dir),
    }


async def list_generated_files(slug: str) -> list[dict[str, Any]]:
    """List all files and directories in the generated agent directory.

    Empty directories are also returned (with content="" and type="dir") so the
    UI explorer can render them — useful for runtime mounts like workspace/.
    """
    from agflow.services.fs_walker import walk_tree

    out_dir = os.path.join(_agents_dir(), slug, "generated")
    results: list[dict[str, Any]] = []
    for entry in walk_tree(out_dir):
        if entry.type == "dir":
            results.append({"path": entry.path, "content": "", "type": "dir"})
            continue
        try:
            with open(entry.full_path, encoding="utf-8") as fh:
                content = fh.read()
        except Exception:
            content = "<binary>"
        results.append({"path": entry.path, "content": content, "type": "file"})
    return results


def _write(directory: str, filename: str, content: str) -> None:
    with open(os.path.join(directory, filename), "w", encoding="utf-8") as f:
        f.write(content)
