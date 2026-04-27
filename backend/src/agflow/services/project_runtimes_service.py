"""project_runtimes + project_group_runtimes — matérialisation d'un déploiement."""
from __future__ import annotations

import json as _json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.runtimes import (
    ProjectGroupRuntimeDetail,
    ProjectGroupRuntimeRow,
    ProjectRuntimeRow,
)

_log = structlog.get_logger(__name__)


class ProjectRuntimeNotFoundError(Exception):
    pass


class ProjectGroupRuntimeNotFoundError(Exception):
    pass


class MachineNotProvisionedError(Exception):
    """Raised when no machine is assigned to (user_id, environment).

    The operator must pre-provision a machine via the admin infra UI before
    a SaaS user can create runtimes.
    """


class ReplicaCountExceedsMaxError(Exception):
    """Raised when a runtime requests more replicas than the group allows.

    The design of a project caps each group's scalability via groups.max_replicas.
    """


def _to_group_runtime(row: dict[str, Any], detail: bool = False) -> ProjectGroupRuntimeRow:
    common = dict(
        id=row["id"],
        seq=row.get("seq", 0),
        project_runtime_id=row["project_runtime_id"],
        group_id=row["group_id"],
        group_name=row.get("group_name", ""),
        machine_id=row.get("machine_id"),
        machine_name=row.get("machine_name", "") or row.get("machine_host", "") or "",
        remote_path=row.get("remote_path", ""),
        status=row.get("status", "pending"),
        pushed_at=row.get("pushed_at"),
        error_message=row.get("error_message"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
    if detail:
        return ProjectGroupRuntimeDetail(
            **common,
            env_text=row.get("env_text", "") or "",
            compose_yaml=row.get("compose_yaml", "") or "",
        )
    return ProjectGroupRuntimeRow(**common)


_GROUP_RUNTIME_SELECT = """
    SELECT
        gr.id, gr.seq, gr.project_runtime_id, gr.group_id, gr.machine_id,
        gr.remote_path, gr.status, gr.pushed_at, gr.error_message,
        gr.created_at, gr.updated_at,
        g.name AS group_name,
        m.name AS machine_name, m.host AS machine_host
    FROM project_group_runtimes gr
    JOIN groups g ON g.id = gr.group_id
    LEFT JOIN infra_machines m ON m.id = gr.machine_id
"""

_GROUP_RUNTIME_DETAIL_SELECT = """
    SELECT
        gr.id, gr.seq, gr.project_runtime_id, gr.group_id, gr.machine_id,
        gr.env_text, gr.compose_yaml, gr.remote_path, gr.status,
        gr.pushed_at, gr.error_message, gr.created_at, gr.updated_at,
        g.name AS group_name,
        m.name AS machine_name, m.host AS machine_host
    FROM project_group_runtimes gr
    JOIN groups g ON g.id = gr.group_id
    LEFT JOIN infra_machines m ON m.id = gr.machine_id
"""


async def list_group_runtimes_by_group(group_id: UUID) -> list[ProjectGroupRuntimeRow]:
    rows = await fetch_all(
        _GROUP_RUNTIME_SELECT
        + " WHERE gr.group_id = $1 AND gr.deleted_at IS NULL ORDER BY gr.seq DESC",
        group_id,
    )
    return [_to_group_runtime(r) for r in rows]


async def get_group_runtime(runtime_id: UUID) -> ProjectGroupRuntimeDetail:
    row = await fetch_one(
        _GROUP_RUNTIME_DETAIL_SELECT + " WHERE gr.id = $1 AND gr.deleted_at IS NULL",
        runtime_id,
    )
    if row is None:
        raise ProjectGroupRuntimeNotFoundError(f"project_group_runtime {runtime_id} not found")
    return _to_group_runtime(row, detail=True)  # type: ignore[return-value]


async def soft_delete_group_runtime(runtime_id: UUID) -> None:
    await execute(
        "UPDATE project_group_runtimes SET deleted_at = now() WHERE id = $1",
        runtime_id,
    )


async def upsert_project_runtime(
    project_id: UUID, deployment_id: UUID, user_id: UUID | None,
) -> tuple[UUID, int]:
    """Create a new project_runtime for this deployment (one per push).

    Returns (runtime_id, seq).
    """
    row = await fetch_one(
        """
        INSERT INTO project_runtimes (project_id, deployment_id, user_id)
        VALUES ($1, $2, $3)
        RETURNING id, seq
        """,
        project_id, deployment_id, user_id,
    )
    assert row is not None
    return row["id"], row["seq"]


async def upsert_group_runtime(
    project_runtime_id: UUID,
    group_id: UUID,
    machine_id: UUID | None,
) -> UUID:
    """Create a group_runtime entry for this runtime×group pair."""
    row = await fetch_one(
        """
        INSERT INTO project_group_runtimes (project_runtime_id, group_id, machine_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (project_runtime_id, group_id) DO UPDATE
            SET machine_id = EXCLUDED.machine_id
        RETURNING id
        """,
        project_runtime_id, group_id, machine_id,
    )
    assert row is not None
    return row["id"]


async def update_group_runtime_push(
    runtime_id: UUID,
    env_text: str,
    compose_yaml: str,
    remote_path: str,
    status: str,
    error_message: str | None = None,
) -> None:
    await execute(
        """
        UPDATE project_group_runtimes
        SET env_text = $2, compose_yaml = $3, remote_path = $4,
            status = $5::varchar, error_message = $6,
            pushed_at = CASE WHEN $5::varchar = 'deployed' THEN now() ELSE pushed_at END
        WHERE id = $1
        """,
        runtime_id, env_text, compose_yaml, remote_path, status, error_message,
    )


async def update_project_runtime_status(
    runtime_id: UUID, status: str, error_message: str | None = None,
) -> None:
    await execute(
        """
        UPDATE project_runtimes
        SET status = $2::varchar, error_message = $3,
            pushed_at = CASE WHEN $2::varchar = 'deployed' THEN now() ELSE pushed_at END
        WHERE id = $1
        """,
        runtime_id, status, error_message,
    )


async def list_runtimes_by_user(user_id: UUID) -> list[ProjectRuntimeRow]:
    """Return all non-deleted runtimes owned by `user_id`, latest first."""
    rows = await fetch_all(
        """
        SELECT
            pr.id, pr.seq, pr.project_id, pr.deployment_id, pr.user_id,
            pr.status, pr.pushed_at, pr.error_message,
            pr.created_at, pr.updated_at,
            u.email AS user_email
        FROM project_runtimes pr
        LEFT JOIN users u ON u.id = pr.user_id
        WHERE pr.user_id = $1 AND pr.deleted_at IS NULL
        ORDER BY pr.seq DESC
        """,
        user_id,
    )
    return [
        ProjectRuntimeRow(
            id=r["id"],
            seq=r.get("seq", 0),
            project_id=r["project_id"],
            deployment_id=r.get("deployment_id"),
            user_id=r.get("user_id"),
            user_email=r.get("user_email"),
            status=r.get("status", "pending"),
            pushed_at=r.get("pushed_at"),
            error_message=r.get("error_message"),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            group_runtimes=[],
        )
        for r in rows
    ]


async def get_runtime(runtime_id: UUID) -> ProjectRuntimeRow:
    """Return a single runtime with its group_runtimes. Raises if not found."""
    r = await fetch_one(
        """
        SELECT
            pr.id, pr.seq, pr.project_id, pr.deployment_id, pr.user_id,
            pr.status, pr.pushed_at, pr.error_message,
            pr.created_at, pr.updated_at,
            u.email AS user_email
        FROM project_runtimes pr
        LEFT JOIN users u ON u.id = pr.user_id
        WHERE pr.id = $1 AND pr.deleted_at IS NULL
        """,
        runtime_id,
    )
    if r is None:
        raise ProjectRuntimeNotFoundError(f"project_runtime {runtime_id} not found")
    groups = await fetch_all(
        _GROUP_RUNTIME_SELECT
        + " WHERE gr.project_runtime_id = $1 AND gr.deleted_at IS NULL ORDER BY g.name",
        runtime_id,
    )
    return ProjectRuntimeRow(
        id=r["id"],
        seq=r.get("seq", 0),
        project_id=r["project_id"],
        deployment_id=r.get("deployment_id"),
        user_id=r.get("user_id"),
        user_email=r.get("user_email"),
        status=r.get("status", "pending"),
        pushed_at=r.get("pushed_at"),
        error_message=r.get("error_message"),
        created_at=r["created_at"],
        updated_at=r["updated_at"],
        group_runtimes=[_to_group_runtime(g) for g in groups],
    )


async def soft_delete_runtime(runtime_id: UUID) -> None:
    """Mark a runtime + its group_runtimes as deleted. The actual `docker
    compose down` and remote cleanup is the caller's responsibility (route
    handler) before invoking this.
    """
    await execute(
        "UPDATE project_runtimes SET deleted_at = now() WHERE id = $1",
        runtime_id,
    )
    await execute(
        """
        UPDATE project_group_runtimes
        SET deleted_at = now()
        WHERE project_runtime_id = $1
        """,
        runtime_id,
    )


async def list_runtimes_by_project(project_id: UUID) -> list[ProjectRuntimeRow]:
    rows = await fetch_all(
        """
        SELECT
            pr.id, pr.seq, pr.project_id, pr.deployment_id, pr.user_id,
            pr.status, pr.pushed_at, pr.error_message,
            pr.created_at, pr.updated_at,
            u.email AS user_email
        FROM project_runtimes pr
        LEFT JOIN users u ON u.id = pr.user_id
        WHERE pr.project_id = $1 AND pr.deleted_at IS NULL
        ORDER BY pr.seq DESC
        """,
        project_id,
    )
    result: list[ProjectRuntimeRow] = []
    for r in rows:
        groups = await fetch_all(
            _GROUP_RUNTIME_SELECT
            + " WHERE gr.project_runtime_id = $1 AND gr.deleted_at IS NULL ORDER BY g.name",
            r["id"],
        )
        result.append(
            ProjectRuntimeRow(
                id=r["id"],
                seq=r.get("seq", 0),
                project_id=r["project_id"],
                deployment_id=r.get("deployment_id"),
                user_id=r.get("user_id"),
                user_email=r.get("user_email"),
                status=r.get("status", "pending"),
                pushed_at=r.get("pushed_at"),
                error_message=r.get("error_message"),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                group_runtimes=[_to_group_runtime(g) for g in groups],
            )
        )
    return result


# ── SaaS runtime creation (public flow) ──────────────────────────────────────


def user_network_name(user_id: UUID) -> str:
    """Convention : a single Docker bridge network per user, shared across
    all of that user's runtimes on the same machine. Phase 1 = single-machine
    per (user, env), so the network is local to that machine.
    """
    return f"agflow-user-{user_id.hex[:8]}"


def runtime_short_id(runtime_id: UUID) -> str:
    """8-char prefix used in container/service hostnames within a runtime."""
    return runtime_id.hex[:8]


async def create_for_user(
    *,
    user_id: UUID,
    project_id: UUID,
    environment: str | None,
    group_selection: dict[UUID, int],
    user_secrets: dict[str, str] | None = None,
) -> UUID:
    """Create a runtime owned by `user_id`, on the user's machine for `environment`.

    Steps:
      1. Validate `replica_count <= groups.max_replicas` for each selected group.
      2. Resolve the target machine via infra_machines_service.get_for_user.
         Raises MachineNotProvisionedError if unmapped — operator must
         pre-provision the (user, environment) machine slot via admin UI.
      3. Insert one project_runtimes row + one project_group_runtimes row per
         selected group (groups with replica_count == 0 are simply skipped —
         we don't insert rows for them so the renderer naturally excludes them).
      4. Compose rendering + SSH push are NOT done here — they are delegated to
         the route handler so it can stream errors back. See
         api/public/runtimes.py.

    Returns the new project_runtime UUID.
    """
    # Lazy imports to avoid cycles (services depend on each other).
    from agflow.services import infra_machines_service

    # 1. Validation : replica_count vs max_replicas
    if group_selection:
        groups = await fetch_all(
            "SELECT id, max_replicas FROM groups WHERE id = ANY($1::uuid[])",
            list(group_selection.keys()),
        )
        max_by_group = {g["id"]: g["max_replicas"] for g in groups}
        for gid, count in group_selection.items():
            if gid not in max_by_group:
                raise ValueError(f"group {gid} not found")
            if count < 0:
                raise ValueError(f"replica_count for group {gid} must be >= 0")
            if count > max_by_group[gid]:
                raise ReplicaCountExceedsMaxError(
                    f"group {gid}: requested {count} replicas, "
                    f"max allowed = {max_by_group[gid]}",
                )

    # 2. Resolve target machine
    machine = await infra_machines_service.get_for_user(user_id, environment)
    if machine is None:
        raise MachineNotProvisionedError(
            f"No machine assigned to (user={user_id}, environment={environment!r}). "
            "Operator must provision one via the admin infra UI.",
        )

    # 3. Insert project_runtime
    runtime_row = await fetch_one(
        """
        INSERT INTO project_runtimes (project_id, user_id, status)
        VALUES ($1, $2, 'pending')
        RETURNING id
        """,
        project_id, user_id,
    )
    assert runtime_row is not None
    runtime_id = runtime_row["id"]

    # 4. Insert one project_group_runtime per SELECTED group (skip count=0)
    for gid, count in group_selection.items():
        if count == 0:
            continue
        await execute(
            """
            INSERT INTO project_group_runtimes
                (project_runtime_id, group_id, machine_id, replica_count, status)
            VALUES ($1, $2, $3, $4, 'pending')
            """,
            runtime_id, gid, machine.id, count,
        )

    _log.info(
        "project_runtimes.create_for_user",
        runtime_id=str(runtime_id),
        user_id=str(user_id),
        project_id=str(project_id),
        environment=environment,
        machine_id=str(machine.id),
        group_count=sum(1 for v in group_selection.values() if v > 0),
    )
    # Stash the user_secrets keys (not values) for traceability — values are
    # consumed by the renderer + push step in the route handler. We could
    # persist them on the runtime row in a future iteration if needed.
    _ = user_secrets

    return runtime_id


# ── Endpoint inspection (factorisation depuis api/admin/project_runtimes.py) ──


async def inspect_endpoints(
    runtime_id: UUID,
) -> list[dict[str, Any]]:
    """SSH-pull the live containers of a runtime via `docker ps --filter
    label=agflow.runtime_id={runtime_id}` and return one entry per container
    with image, host:ports mapping, and status.

    Used by both admin status route and the public /endpoints API.
    """
    # Lazy imports to avoid cycles.
    from agflow.services import (
        infra_certificates_service,
        infra_machines_service,
        ssh_executor,
    )

    # Find one machine (all group_runtimes of a runtime share the same machine
    # in Phase 1). If multiple, we'd query each — but that's Phase 2.
    row = await fetch_one(
        """
        SELECT DISTINCT machine_id
        FROM project_group_runtimes
        WHERE project_runtime_id = $1 AND deleted_at IS NULL
          AND machine_id IS NOT NULL
        LIMIT 1
        """,
        runtime_id,
    )
    if row is None or row.get("machine_id") is None:
        return []

    machine_id = row["machine_id"]
    machine = await infra_machines_service.get_by_id(machine_id)
    creds = await infra_machines_service.get_credentials(machine_id)
    private_key = None
    passphrase = None
    if creds.get("certificate_id"):
        cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
        private_key = cert.get("private_key")
        passphrase = cert.get("passphrase")

    cmd = (
        f"docker ps -a --filter 'label=agflow.runtime_id={runtime_id}' "
        f"--format '{{{{json .}}}}'"
    )
    try:
        result = await ssh_executor.exec_command(
            host=creds["host"], port=creds["port"],
            username=creds["username"], password=creds["password"],
            private_key=private_key, passphrase=passphrase,
            command=cmd,
        )
    except ssh_executor.SSHConnectionError as exc:
        _log.warning("inspect_endpoints.ssh_failed", runtime_id=str(runtime_id), error=str(exc))
        return []

    endpoints: list[dict[str, Any]] = []
    for line in (result.get("stdout") or "").strip().split("\n"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        endpoints.append(
            {
                "container_name": entry.get("Names", ""),
                "image": entry.get("Image", ""),
                "host": machine.host,
                "ports": _parse_docker_ports(entry.get("Ports", "")),
                "status": _normalize_state(entry.get("State", "")),
                "raw_status": entry.get("Status", ""),
            }
        )
    return endpoints


def _parse_docker_ports(ports_str: str) -> list[dict[str, int | str]]:
    """Parse `docker ps` Ports column.

    Examples:
      "0.0.0.0:32785->9000/tcp, [::]:32785->9000/tcp"
        → [{"host": 32785, "container": 9000, "protocol": "tcp"}]
      "9000/tcp"  → [{"container": 9000, "protocol": "tcp"}]   (no host bind)
    """
    out: list[dict[str, int | str]] = []
    seen: set[tuple[int, int, str]] = set()
    for piece in ports_str.split(","):
        piece = piece.strip()
        if not piece:
            continue
        # Split protocol
        if "/" in piece:
            mapping, proto = piece.rsplit("/", 1)
        else:
            mapping, proto = piece, "tcp"
        host_port: int | None = None
        container_port: int | None = None
        if "->" in mapping:
            host_part, container_part = mapping.rsplit("->", 1)
            # host_part = "0.0.0.0:32785" or "[::]:32785"
            try:
                host_port = int(host_part.rsplit(":", 1)[-1])
            except ValueError:
                host_port = None
            try:
                container_port = int(container_part)
            except ValueError:
                container_port = None
        else:
            try:
                container_port = int(mapping)
            except ValueError:
                container_port = None
        if container_port is None:
            continue
        key = (host_port or 0, container_port, proto)
        if key in seen:
            continue
        seen.add(key)
        entry: dict[str, int | str] = {"container": container_port, "protocol": proto}
        if host_port is not None:
            entry["host"] = host_port
        out.append(entry)
    return out


def _normalize_state(state: str) -> str:
    low = (state or "").lower()
    if "running" in low or "up" in low:
        return "running"
    if "exited" in low or "stopped" in low:
        return "stopped"
    if "created" in low:
        return "created"
    if "restarting" in low:
        return "restarting"
    return low or "unknown"
