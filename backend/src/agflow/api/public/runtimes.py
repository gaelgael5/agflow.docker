"""Public SaaS runtime API.

Owner-scoped CRUD over runtimes. A runtime materialises a project blueprint
on the user's dedicated machine for an environment, with selectable groups
and replica counts.

ACL pattern : `WHERE user_id = ctx.owner_id OR is_admin` — same as sessions.
"""
from __future__ import annotations

import re
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, status

from agflow.auth.api_key import require_api_key
from agflow.auth.context import AuthContext
from agflow.db.pool import fetch_all, fetch_one
from agflow.schemas.runtimes_public import (
    GroupRuntimeOut,
    RuntimeCreate,
    RuntimeEndpoint,
    RuntimeOut,
    parse_endpoints,
)
from agflow.services import (
    compose_renderer_service,
    infra_certificates_service,
    infra_machines_service,
    project_runtimes_service,
    projects_service,
    secrets_service,
    ssh_executor,
)

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["public-runtimes"])


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _assert_runtime_owned(runtime_id: UUID, ctx: AuthContext) -> dict:
    """Return the runtime row if (a) it exists, (b) caller owns it OR is admin.

    Raises 404 in all other cases (don't leak existence to non-owners).
    """
    row = await fetch_one(
        """
        SELECT id, project_id, user_id, status, deployment_id
        FROM project_runtimes
        WHERE id = $1 AND deleted_at IS NULL
        """,
        runtime_id,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "runtime not found")
    if not ctx.is_admin and row["user_id"] != ctx.owner_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "runtime not found")
    return dict(row)


def _runtime_out(row: dict, group_runtimes: list[dict]) -> RuntimeOut:
    return RuntimeOut(
        id=row["id"],
        seq=row.get("seq", 0),
        project_id=row["project_id"],
        user_id=row.get("user_id"),
        status=row.get("status", "pending"),
        pushed_at=row.get("pushed_at"),
        error_message=row.get("error_message"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        group_runtimes=[
            GroupRuntimeOut(
                id=g["id"],
                group_id=g["group_id"],
                group_name=g.get("group_name", ""),
                replica_count=g.get("replica_count", 1),
                machine_id=g.get("machine_id"),
                status=g.get("status", "pending"),
                pushed_at=g.get("pushed_at"),
                error_message=g.get("error_message"),
            )
            for g in group_runtimes
        ],
    )


_ENV_LITERAL_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _build_env_text(env_var_names: list[str], user_secrets: dict[str, str], platform: dict[str, str]) -> str:
    """Build the .env content. user_secrets > platform > empty (let docker fail with explicit log)."""
    lines: list[str] = []
    missing: list[str] = []
    for name in env_var_names:
        if name in user_secrets:
            value = user_secrets[name]
        elif name in platform:
            value = platform[name]
        else:
            value = ""
            missing.append(name)
        # Escape $, ` and " minimally in env values; docker compose handles the rest.
        # We don't quote-wrap because compose accepts both forms; we ensure no newlines.
        safe = value.replace("\n", "\\n")
        lines.append(f"{name}={safe}")
    if missing:
        _log.warning("public.runtimes.missing_env_vars", missing=missing)
    return "\n".join(lines) + ("\n" if lines else "")


# ── Routes ───────────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/runtimes",
    response_model=RuntimeOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_runtime(
    project_id: UUID,
    body: RuntimeCreate,
    api_key: dict = require_api_key("runtimes:write"),  # noqa: B008
) -> RuntimeOut:
    ctx = AuthContext.from_api_key(api_key)

    # Verify the project exists (catalogue is global so anyone with the scope
    # can target any project).
    try:
        await projects_service.get_by_id(project_id)
    except projects_service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    # 1. Create the runtime row + group_runtime rows (validates replica_count).
    group_selection = {
        gid: entry.replica_count for gid, entry in body.groups.items()
    }
    if not any(c > 0 for c in group_selection.values()):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "at least one group must have replica_count > 0",
        )

    try:
        runtime_id = await project_runtimes_service.create_for_user(
            user_id=ctx.owner_id,
            project_id=project_id,
            environment=body.environment,
            group_selection=group_selection,
            user_secrets=body.user_secrets,
        )
    except project_runtimes_service.ReplicaCountExceedsMaxError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except project_runtimes_service.MachineNotProvisionedError as exc:
        raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    # 2. Lookup user's machine + network name.
    machine = await infra_machines_service.get_for_user(ctx.owner_id, body.environment)
    if machine is None:
        # Defensive — should have been caught above by create_for_user.
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            f"machine not provisioned for (user, environment={body.environment!r})",
        )
    network_name = project_runtimes_service.user_network_name(ctx.owner_id)

    # 3. Render compose YAML + collect ${VAR} refs.
    try:
        compose_yaml, env_var_names = await compose_renderer_service.render_for_runtime(
            runtime_id, user_network=network_name,
        )
    except compose_renderer_service.ComposeRenderError as exc:
        await project_runtimes_service.update_project_runtime_status(
            runtime_id, "failed", str(exc),
        )
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc

    # 4. Build .env (user_secrets > platform secrets > empty).
    platform_secrets: dict[str, str] = {}
    for s in await secrets_service.list_all():
        revealed = await secrets_service.reveal(s.id)
        platform_secrets[s.var_name] = revealed.value
    env_text = _build_env_text(env_var_names, body.user_secrets, platform_secrets)

    # 5. SSH ensure-network + push compose.
    creds = await infra_machines_service.get_credentials(machine.id)
    private_key = None
    passphrase = None
    if creds.get("certificate_id"):
        cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
        private_key = cert.get("private_key")
        passphrase = cert.get("passphrase")
    ssh_kwargs = {
        "host": creds["host"], "port": creds["port"],
        "username": creds["username"], "password": creds["password"],
        "private_key": private_key, "passphrase": passphrase,
    }

    remote_dir = f"~/agflow.docker/runtimes/{runtime_id}"
    ensure_network_cmd = (
        f"docker network inspect {network_name} >/dev/null 2>&1 "
        f"|| docker network create {network_name}"
    )

    steps: list[tuple[str, str, str | None]] = [
        ("ensure_network", ensure_network_cmd, None),
        ("mkdir", f"mkdir -p {remote_dir}", None),
        ("write_compose", f"cat > {remote_dir}/docker-compose.yml", compose_yaml),
        ("write_env", f"cat > {remote_dir}/.env", env_text),
        ("compose_up", f"cd {remote_dir} && docker compose up -d", None),
    ]

    failed_step: str | None = None
    last_stderr = ""
    for step_name, cmd, stdin in steps:
        try:
            result = await ssh_executor.exec_command(
                **ssh_kwargs, command=cmd, input=stdin,
            )
        except Exception as exc:
            failed_step = step_name
            last_stderr = str(exc)
            break
        if result.get("exit_code") != 0:
            failed_step = step_name
            last_stderr = result.get("stderr", "") or ""
            break

    final_status = "deployed" if failed_step is None else "failed"
    error_msg = (
        None
        if failed_step is None
        else f"failed at step {failed_step}: {last_stderr[:500]}"
    )
    await project_runtimes_service.update_project_runtime_status(
        runtime_id, final_status, error_msg,
    )
    # Update each group_runtime row to reflect deployment outcome.
    rows = await fetch_all(
        "SELECT id FROM project_group_runtimes WHERE project_runtime_id = $1 AND deleted_at IS NULL",
        runtime_id,
    )
    for r in rows:
        await project_runtimes_service.update_group_runtime_push(
            runtime_id=r["id"],
            env_text=env_text,
            compose_yaml=compose_yaml,
            remote_path=remote_dir,
            status=final_status,
            error_message=error_msg,
        )

    if failed_step is not None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"deployment failed at {failed_step}: {last_stderr[:300]}",
        )

    return await get_runtime(runtime_id, api_key)


@router.get("/runtimes", response_model=list[RuntimeOut])
async def list_runtimes(
    api_key: dict = require_api_key("runtimes:read"),  # noqa: B008
) -> list[RuntimeOut]:
    ctx = AuthContext.from_api_key(api_key)
    if ctx.is_admin:
        # Admin sees all (paginated TODO if it grows).
        rows = await fetch_all(
            """
            SELECT id, seq, project_id, deployment_id, user_id,
                   status, pushed_at, error_message, created_at, updated_at
            FROM project_runtimes
            WHERE deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT 200
            """,
        )
    else:
        rows = await fetch_all(
            """
            SELECT id, seq, project_id, deployment_id, user_id,
                   status, pushed_at, error_message, created_at, updated_at
            FROM project_runtimes
            WHERE user_id = $1 AND deleted_at IS NULL
            ORDER BY created_at DESC
            """,
            ctx.owner_id,
        )
    return [_runtime_out(dict(r), []) for r in rows]


@router.get("/runtimes/{runtime_id}", response_model=RuntimeOut)
async def get_runtime(
    runtime_id: UUID,
    api_key: dict = require_api_key("runtimes:read"),  # noqa: B008
) -> RuntimeOut:
    ctx = AuthContext.from_api_key(api_key)
    await _assert_runtime_owned(runtime_id, ctx)
    full = await project_runtimes_service.get_runtime(runtime_id)
    return RuntimeOut(
        id=full.id,
        seq=full.seq,
        project_id=full.project_id,
        user_id=full.user_id,
        status=full.status,
        pushed_at=full.pushed_at,
        error_message=full.error_message,
        created_at=full.created_at,
        updated_at=full.updated_at,
        group_runtimes=[
            GroupRuntimeOut(
                id=g.id,
                group_id=g.group_id,
                group_name=g.group_name,
                replica_count=getattr(g, "replica_count", 1),
                machine_id=g.machine_id,
                status=g.status,
                pushed_at=g.pushed_at,
                error_message=g.error_message,
            )
            for g in full.group_runtimes
        ],
    )


@router.get(
    "/runtimes/{runtime_id}/endpoints",
    response_model=list[RuntimeEndpoint],
)
async def list_runtime_endpoints(
    runtime_id: UUID,
    api_key: dict = require_api_key("runtimes:read"),  # noqa: B008
) -> list[RuntimeEndpoint]:
    ctx = AuthContext.from_api_key(api_key)
    await _assert_runtime_owned(runtime_id, ctx)
    raw = await project_runtimes_service.inspect_endpoints(runtime_id)
    return parse_endpoints(raw)


@router.delete(
    "/runtimes/{runtime_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_runtime(
    runtime_id: UUID,
    api_key: dict = require_api_key("runtimes:delete"),  # noqa: B008
) -> None:
    ctx = AuthContext.from_api_key(api_key)
    await _assert_runtime_owned(runtime_id, ctx)

    # Best-effort `docker compose down` on the user's machine for this runtime.
    rows = await fetch_all(
        """
        SELECT DISTINCT machine_id, remote_path
        FROM project_group_runtimes
        WHERE project_runtime_id = $1 AND deleted_at IS NULL
          AND machine_id IS NOT NULL AND remote_path != ''
        """,
        runtime_id,
    )
    for r in rows:
        try:
            creds = await infra_machines_service.get_credentials(r["machine_id"])
        except Exception as exc:
            _log.warning(
                "public.runtimes.delete.creds_failed",
                runtime_id=str(runtime_id), machine_id=str(r["machine_id"]),
                error=str(exc),
            )
            continue
        private_key = None
        passphrase = None
        if creds.get("certificate_id"):
            cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
            private_key = cert.get("private_key")
            passphrase = cert.get("passphrase")
        try:
            await ssh_executor.exec_command(
                host=creds["host"], port=creds["port"],
                username=creds["username"], password=creds["password"],
                private_key=private_key, passphrase=passphrase,
                command=f"cd {r['remote_path']} && docker compose down -v --remove-orphans || true",
            )
        except Exception as exc:
            _log.warning(
                "public.runtimes.delete.ssh_failed",
                runtime_id=str(runtime_id), error=str(exc),
            )

    await project_runtimes_service.soft_delete_runtime(runtime_id)
    _log.info("public.runtimes.deleted", runtime_id=str(runtime_id), user_id=str(ctx.owner_id))
