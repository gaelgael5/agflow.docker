from __future__ import annotations

import json
import os
import re
import secrets
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import aiodocker
import structlog

from agflow.schemas.containers import ContainerInfo

_log = structlog.get_logger(__name__)

# How many agflow-managed containers can run at once. Hard limit to avoid
# accidental resource exhaustion on the test LXC.
MAX_RUNNING_CONTAINERS = 10

_AGFLOW_MANAGED_LABEL = "agflow.managed"
_AGFLOW_DOCKERFILE_LABEL = "agflow.dockerfile_id"
_AGFLOW_INSTANCE_LABEL = "agflow.instance_id"

_TEMPLATE_RE = re.compile(r"\{(\w+)\}")
# Matches ${VAR} and ${VAR:-default} — standard shell templating that the
# user would expect to be expanded before docker sees it. Because we call
# docker via HTTP API (no shell in between), we do the expansion ourselves
# against os.environ.
_SHELL_VAR_RE = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


async def _load_platform_secrets() -> dict[str, str]:
    """Load all global platform secrets as a dict for env var injection."""
    from agflow.config import get_settings
    from agflow.db.pool import fetch_all

    master = get_settings().secrets_master_key
    rows = await fetch_all(
        """
        SELECT var_name, pgp_sym_decrypt(value_encrypted, $1) AS value
        FROM secrets
        WHERE scope = 'global'
        """,
        master,
    )
    return {r["var_name"]: r["value"] for r in rows}


class ContainerRunnerError(Exception):
    """Base class for predictable errors raised by the runner."""


class ImageNotBuiltError(ContainerRunnerError):
    pass


class TooManyContainersError(ContainerRunnerError):
    pass


class ContainerNotFoundError(ContainerRunnerError):
    pass


class InvalidParamsError(ContainerRunnerError):
    pass


# ─────────────────────────────────────────────────────────────
# Template resolver — mirrors the frontend semantics:
#   {KEY}      → lookup in vars, recursive until stable
#   ${VAR}     → left untouched (shell-level templating)
# ─────────────────────────────────────────────────────────────
def resolve_templates(
    s: str, vars: dict[str, str], max_iter: int = 16
) -> str:
    if not s:
        return s
    current = s
    for _ in range(max_iter):
        next_val = _TEMPLATE_RE.sub(
            lambda m: vars.get(m.group(1), m.group(0)), current
        )
        if next_val == current:
            return next_val
        current = next_val
    return current


def expand_shell_vars(s: str, extra_env: dict[str, str] | None = None) -> str:
    """Expand ${VAR} and ${VAR:-default} against os.environ + extra_env.

    Called AFTER agflow's own {KEY} resolution. Missing env vars fall back
    to the ``:-default`` clause if present, otherwise to an empty string.
    """
    if not s:
        return s
    merged = {**os.environ, **(extra_env or {})}
    return _SHELL_VAR_RE.sub(
        lambda m: merged.get(m.group(1), m.group(2) or ""),
        s,
    )


def full_resolve(
    s: str, vars: dict[str, str], extra_env: dict[str, str] | None = None
) -> str:
    """agflow {KEY} templating followed by shell ${VAR} expansion."""
    return expand_shell_vars(resolve_templates(s, vars), extra_env)


def _data_host_dir() -> str:
    return os.environ.get("AGFLOW_DATA_HOST_DIR", "/app/data").rstrip("/")


def _data_container_dir() -> str:
    return os.environ.get("AGFLOW_DATA_DIR", "/app/data").rstrip("/")


def resolve_mount_source(
    raw_source: str,
    dockerfile_id: str,
    vars: dict[str, str],
    extra_env: dict[str, str] | None = None,
) -> tuple[str, str | None, bool]:
    """Resolve a user-supplied mount source to the path Docker should use.

    Returns a triplet:
      * host_path          — the absolute host path to pass to Docker.
      * container_path     — same file as seen from the backend container,
                             used for existence checks. ``None`` if the
                             resolved source was already absolute (we don't
                             reach into arbitrary host paths from here).
      * auto_prefixed      — True if we auto-prefixed the source under
                             ``{HOST_DIR}/{slug}/``; False if it was kept
                             as-is because it was already absolute.

    Rules:
      1. Run the full templating (agflow {KEY} + shell ${VAR}) first.
      2. If the resolved path starts with ``/`` → keep as-is (user wants an
         explicit host path). No auto-prefix, no existence check.
      3. Otherwise → strip any leading ``./`` and prepend
         ``{AGFLOW_DATA_HOST_DIR}/{slug}/``. The same path under
         ``{AGFLOW_DATA_DIR}/{slug}/`` is returned for existence checks.
    """
    resolved = full_resolve(raw_source, vars, extra_env).strip()
    if resolved.startswith("/"):
        return resolved, None, False

    if resolved.startswith("./"):
        resolved = resolved[2:]
    resolved = resolved.lstrip("/")

    host_path = f"{_data_host_dir()}/{dockerfile_id}/{resolved}"
    container_path = f"{_data_container_dir()}/{dockerfile_id}/{resolved}"
    return host_path, container_path, True


def check_mount_source(container_path: str | None) -> bool | None:
    """Existence check for an auto-prefixed mount source.

    Returns ``True`` / ``False`` if the path can be checked via the backend
    container's view of the data dir, or ``None`` for absolute paths that
    were passed through (we can't reach host-only paths from here).
    """
    if container_path is None:
        return None
    return os.path.isfile(container_path) or os.path.isdir(container_path)


def _looks_like_directory(path: str) -> bool:
    """Heuristic: a path segment with a '.' in its name is treated as a file
    (e.g. ``auth.json``, ``.env``, ``config.yml``). Everything else is
    treated as a directory and will be auto-created at launch time.
    """
    tail = path.rsplit("/", 1)[-1]
    return "." not in tail


def _ensure_mount_paths_from_config(
    dockerfile_id: str,
    params_json_content: str,
    instance_id: str,
    content_hash: str,
) -> None:
    """Helper that reparses Dockerfile.json and calls ensure_mount_paths."""
    try:
        root = json.loads(params_json_content) if params_json_content else {}
    except json.JSONDecodeError:
        return
    if not isinstance(root, dict):
        return
    docker_cfg = root.get("docker") or {}
    params = root.get("Params") or {}
    mounts = docker_cfg.get("Mounts") if isinstance(docker_cfg, dict) else None
    if not isinstance(mounts, list):
        return
    user_vars = {
        k: str(v) for k, v in params.items() if isinstance(v, (str, int, float))
    } if isinstance(params, dict) else {}
    system_vars = {
        "slug": dockerfile_id,
        "hash": content_hash,
        "id": instance_id,
    }
    try:
        ensure_mount_paths(dockerfile_id, mounts, {**user_vars, **system_vars})
    except OSError as exc:
        _log.warning(
            "container.ensure_mount_paths.failed",
            dockerfile_id=dockerfile_id,
            error=str(exc),
        )


def ensure_mount_paths(
    dockerfile_id: str,
    mounts: list[dict[str, Any]],
    vars: dict[str, str],
) -> list[str]:
    """For each auto-prefixed mount, pre-create the parent directory and,
    for directory-like sources, the destination itself.

    This lets the user use `workspace` as a mount source without having to
    `mkdir -p` first — the directory appears on the host at launch time.
    For file sources (e.g. `auth.json`), only the parent is created, so the
    user still has to place the actual file.

    Returns a list of warnings for mounts that could not be auto-prepared
    (e.g. file sources that still don't exist after ensuring the parent).
    """
    warnings: list[str] = []
    for m in mounts:
        if not isinstance(m, dict):
            continue
        raw_source = str(m.get("source", "")).strip()
        if not raw_source:
            continue
        _host, container_path, auto_prefixed = resolve_mount_source(
            raw_source, dockerfile_id, vars
        )
        if not auto_prefixed or container_path is None:
            continue
        try:
            if _looks_like_directory(container_path):
                os.makedirs(container_path, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(container_path), exist_ok=True)
                if not os.path.exists(container_path):
                    warnings.append(
                        f"Mount source file is missing: {container_path} "
                        f"(parent directory was prepared — place the file there)"
                    )
        except OSError as exc:
            warnings.append(
                f"Could not create mount path {container_path}: {exc}"
            )
    return warnings


def _resolve_list(
    items: list[dict[str, Any]] | None,
    vars: dict[str, str],
    extra_env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not items:
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        resolved: dict[str, Any] = {}
        for k, v in item.items():
            if isinstance(v, str):
                resolved[k] = full_resolve(v, vars, extra_env)
            else:
                resolved[k] = v
        out.append(resolved)
    return out


def _resolve_dict(
    d: dict[str, Any] | None,
    vars: dict[str, str],
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    if not d:
        return {}
    out: dict[str, str] = {}
    for k, v in d.items():
        if isinstance(v, str):
            out[k] = full_resolve(v, vars, extra_env)
        else:
            out[k] = str(v)
    return out


# ─────────────────────────────────────────────────────────────
# Resource parsers
# ─────────────────────────────────────────────────────────────
_MEMORY_UNITS = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def parse_memory_bytes(raw: str) -> int:
    """Parse docker-style memory like '512m', '2g', '1024k' to bytes.
    Returns 0 if the string is empty or 0 — means 'no limit'.
    """
    s = (raw or "").strip().lower()
    if not s:
        return 0
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([bkmg]?)$", s)
    if not m:
        raise InvalidParamsError(f"Invalid memory value: '{raw}'")
    value = float(m.group(1))
    if value <= 0:
        return 0
    unit = m.group(2) or "b"
    return int(value * _MEMORY_UNITS[unit])


def parse_nano_cpus(raw: str) -> int:
    """Parse docker-style cpu count like '1.5' to nano CPUs (1 CPU = 1e9)."""
    s = (raw or "").strip()
    if not s:
        return 0
    try:
        value = float(s)
    except ValueError as exc:
        raise InvalidParamsError(f"Invalid cpu value: '{raw}'") from exc
    if value <= 0:
        return 0
    return int(value * 1_000_000_000)


# ─────────────────────────────────────────────────────────────
# Build docker run config from Dockerfile.json + current hash
# ─────────────────────────────────────────────────────────────
def build_run_config(
    *,
    dockerfile_id: str,
    params_json_content: str,
    content_hash: str,
    instance_id: str,
    extra_env: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Parse Dockerfile.json and produce (container_name, aiodocker config).

    The returned config follows the Docker Engine API payload shape expected
    by `aiodocker.Docker().containers.create(config=..., name=...)`.
    """
    try:
        root = json.loads(params_json_content) if params_json_content else {}
    except json.JSONDecodeError as exc:
        raise InvalidParamsError(
            f"Dockerfile.json is not valid JSON: {exc.msg}"
        ) from exc

    if not isinstance(root, dict):
        raise InvalidParamsError("Dockerfile.json root must be an object")

    docker_cfg = root.get("docker") or {}
    params = root.get("Params") or {}
    if not isinstance(docker_cfg, dict) or not isinstance(params, dict):
        raise InvalidParamsError(
            "Dockerfile.json must have 'docker' and 'Params' objects"
        )

    # Resolution variables — user Params first, then system vars (system
    # values always win over user-defined ones).
    user_vars: dict[str, str] = {
        k: str(v) for k, v in params.items() if isinstance(v, (str, int, float))
    }
    system_vars = {
        "slug": dockerfile_id,
        "hash": content_hash,
        "id": instance_id,
    }
    vars_map = {**user_vars, **system_vars}

    container = docker_cfg.get("Container") or {}
    network = docker_cfg.get("Network") or {}
    runtime = docker_cfg.get("Runtime") or {}
    resources = docker_cfg.get("Resources") or {}
    environments = docker_cfg.get("Environments") or {}
    mounts = docker_cfg.get("Mounts") or []

    name = full_resolve(str(container.get("Name", "")), vars_map, extra_env).strip()
    if not name:
        raise InvalidParamsError("Container.Name template resolved to empty")

    # Environment vars: docker expects list of "KEY=VALUE".
    env_dict = _resolve_dict(
        environments if isinstance(environments, dict) else {}, vars_map, extra_env
    )
    env_list = [f"{k}={v}" for k, v in env_dict.items()]

    # Mounts → Binds ("source:target[:ro]"). Source goes through the
    # auto-prefix + shell-expand pipeline; target is a literal container
    # path after {KEY} + ${VAR} resolution.
    raw_mounts = mounts if isinstance(mounts, list) else []
    binds: list[str] = []
    for m in raw_mounts:
        if not isinstance(m, dict):
            continue
        raw_source = str(m.get("source", "")).strip()
        target = full_resolve(str(m.get("target", "")).strip(), vars_map, extra_env)
        if not raw_source or not target:
            continue
        host_source, _container_path, _auto = resolve_mount_source(
            raw_source, dockerfile_id, vars_map, extra_env
        )
        ro_flag = ":ro" if bool(m.get("readonly")) else ""
        binds.append(f"{host_source}:{target}{ro_flag}")

    network_mode = full_resolve(
        str(network.get("Mode", "bridge")), vars_map, extra_env
    ) or "bridge"

    memory_bytes = parse_memory_bytes(str(resources.get("Memory", "")))
    nano_cpus = parse_nano_cpus(str(resources.get("Cpus", "")))

    stop_signal = str(runtime.get("StopSignal", "SIGTERM")) or "SIGTERM"
    stop_timeout_raw = runtime.get("StopTimeout", 30)
    try:
        stop_timeout = int(stop_timeout_raw)
    except (TypeError, ValueError) as exc:
        raise InvalidParamsError(
            f"Runtime.StopTimeout must be an integer, got {stop_timeout_raw!r}"
        ) from exc
    working_dir = full_resolve(str(runtime.get("WorkingDir", "")), vars_map, extra_env) or None
    init_enabled = bool(runtime.get("Init", True))

    image_template = str(
        container.get("Image", f"agflow-{dockerfile_id}:{{hash}}")
    )
    image = full_resolve(image_template, vars_map, extra_env)

    host_config: dict[str, Any] = {
        "NetworkMode": network_mode,
        "Init": init_enabled,
        "Binds": binds,
        "AutoRemove": False,
    }
    if memory_bytes > 0:
        host_config["Memory"] = memory_bytes
    if nano_cpus > 0:
        host_config["NanoCpus"] = nano_cpus
    if stop_timeout >= 0:
        host_config["StopTimeout"] = stop_timeout

    labels = {
        _AGFLOW_MANAGED_LABEL: "true",
        _AGFLOW_DOCKERFILE_LABEL: dockerfile_id,
        _AGFLOW_INSTANCE_LABEL: instance_id,
    }

    config: dict[str, Any] = {
        "Image": image,
        "Env": env_list,
        "Labels": labels,
        "StopSignal": stop_signal,
        "Tty": False,
        "OpenStdin": False,
        "HostConfig": host_config,
    }
    if working_dir:
        config["WorkingDir"] = working_dir

    return name, config


# ─────────────────────────────────────────────────────────────
# Container lifecycle via aiodocker
# ─────────────────────────────────────────────────────────────
def _parse_docker_ts(raw: str) -> datetime:
    # Docker returns ISO-8601 with nanosecond precision; trim to microseconds
    # so datetime.fromisoformat is happy. "2024-01-02T03:04:05.123456789Z"
    # → "2024-01-02T03:04:05.123456+00:00".
    s = raw.rstrip("Z")
    if "." in s:
        head, frac = s.split(".", 1)
        frac = frac[:6]
        s = f"{head}.{frac}"
    return datetime.fromisoformat(s + "+00:00")


def _info_from_container(raw: dict[str, Any]) -> ContainerInfo:
    labels = raw.get("Labels") or {}
    names = raw.get("Names") or []
    name = (names[0] if names else raw.get("Name", "")).lstrip("/")
    created = raw.get("Created")
    if isinstance(created, (int, float)):
        created_at = datetime.fromtimestamp(created)
    elif isinstance(created, str):
        created_at = _parse_docker_ts(created)
    else:
        created_at = datetime.now()
    return ContainerInfo(
        id=raw.get("Id", raw.get("ID", "")),
        name=name,
        dockerfile_id=labels.get(_AGFLOW_DOCKERFILE_LABEL, ""),
        image=raw.get("Image", ""),
        status=raw.get("State", "created"),
        created_at=created_at,
        instance_id=labels.get(_AGFLOW_INSTANCE_LABEL, ""),
    )


async def list_running() -> list[ContainerInfo]:
    """List all agflow-managed containers (running or stopped)."""
    docker = aiodocker.Docker()
    try:
        containers = await docker.containers.list(
            all=True,
            filters={"label": [f"{_AGFLOW_MANAGED_LABEL}=true"]},
        )
        result: list[ContainerInfo] = []
        for c in containers:
            # Show() returns the full inspect payload which has Config.Labels.
            inspect = await c.show()
            cfg = inspect.get("Config") or {}
            state = inspect.get("State") or {}
            labels = cfg.get("Labels") or {}
            created_at = _parse_docker_ts(inspect.get("Created", ""))
            result.append(
                ContainerInfo(
                    id=inspect.get("Id", ""),
                    name=(inspect.get("Name") or "").lstrip("/"),
                    dockerfile_id=labels.get(_AGFLOW_DOCKERFILE_LABEL, ""),
                    image=cfg.get("Image", ""),
                    status=state.get("Status", "created"),
                    created_at=created_at,
                    instance_id=labels.get(_AGFLOW_INSTANCE_LABEL, ""),
                )
            )
        return result
    finally:
        await docker.close()


async def start(
    dockerfile_id: str,
    *,
    params_json_content: str,
    content_hash: str,
    user_secrets: dict[str, str] | None = None,
) -> ContainerInfo:
    """Create and start a container for a given dockerfile.

    Raises:
        ImageNotBuiltError: the target image does not exist yet.
        TooManyContainersError: the hard limit of running containers is reached.
        InvalidParamsError: Dockerfile.json cannot be translated to a config.
    """
    # Enforce concurrency limit before touching docker.
    existing = await list_running()
    alive = [c for c in existing if c.status in ("running", "created", "restarting")]
    if len(alive) >= MAX_RUNNING_CONTAINERS:
        raise TooManyContainersError(
            f"Maximum of {MAX_RUNNING_CONTAINERS} running containers reached. "
            f"Stop one before launching another."
        )

    instance_id = secrets.token_hex(3)
    platform_secrets = await _load_platform_secrets()
    name, config = build_run_config(
        dockerfile_id=dockerfile_id,
        params_json_content=params_json_content,
        content_hash=content_hash,
        instance_id=instance_id,
        extra_env=platform_secrets,
    )

    # Pre-create auto-prefixed mount directories so the default workspace/
    # output/... mounts "just work" without the user having to mkdir first.
    _ensure_mount_paths_from_config(
        dockerfile_id, params_json_content, instance_id, content_hash
    )

    if user_secrets:
        existing_env = config.get("Env", [])
        for k, v in user_secrets.items():
            existing_env.append(f"{k}={v}")
        config["Env"] = existing_env

    docker = aiodocker.Docker()
    try:
        try:
            await docker.images.inspect(config["Image"])
        except aiodocker.exceptions.DockerError as exc:
            if exc.status == 404:
                raise ImageNotBuiltError(
                    f"Image '{config['Image']}' not found — build the dockerfile first."
                ) from exc
            raise

        container = await docker.containers.create(config=config, name=name)
        await container.start()
        inspect = await container.show()

        cfg = inspect.get("Config") or {}
        state = inspect.get("State") or {}
        labels = cfg.get("Labels") or {}
        info = ContainerInfo(
            id=inspect.get("Id", ""),
            name=(inspect.get("Name") or "").lstrip("/"),
            dockerfile_id=labels.get(_AGFLOW_DOCKERFILE_LABEL, dockerfile_id),
            image=cfg.get("Image", config["Image"]),
            status=state.get("Status", "running"),
            created_at=_parse_docker_ts(inspect.get("Created", "")),
            instance_id=labels.get(_AGFLOW_INSTANCE_LABEL, instance_id),
        )
        _log.info(
            "container.start",
            dockerfile_id=dockerfile_id,
            container_id=info.id,
            name=info.name,
        )
        return info
    finally:
        await docker.close()


async def run_task(
    dockerfile_id: str,
    *,
    params_json_content: str,
    content_hash: str,
    task_payload: dict[str, Any],
    timeout_seconds: int = 600,
    user_secrets: dict[str, str] | None = None,
    on_container_started: Any | None = None,
) -> "AsyncIterator[dict[str, Any]]":
    """One-shot: start a container, feed the task on stdin, stream stdout events.

    Yields parsed event dicts as they arrive, plus a final
    ``{"type": "result", "status": "success" | "failure", "exit_code": N}``.

    The container is removed after exit. Mirrors the M1 entrypoint protocol
    (JSON in, newline-delimited JSON events out).
    """
    import asyncio as _asyncio
    import json as _json
    import aiodocker as _aiodocker

    # Concurrency guard — shares the same limit as interactive containers.
    existing = await list_running()
    alive = [
        c for c in existing if c.status in ("running", "created", "restarting")
    ]
    if len(alive) >= MAX_RUNNING_CONTAINERS:
        raise TooManyContainersError(
            f"Maximum of {MAX_RUNNING_CONTAINERS} running containers reached."
        )

    instance_id = secrets.token_hex(3)
    platform_secrets = await _load_platform_secrets()
    name, config = build_run_config(
        dockerfile_id=dockerfile_id,
        params_json_content=params_json_content,
        content_hash=content_hash,
        instance_id=instance_id,
        extra_env=platform_secrets,
    )
    _ensure_mount_paths_from_config(
        dockerfile_id, params_json_content, instance_id, content_hash
    )

    # Prepare the JSON payload for stdin piping. The actual ENTRYPOINT path
    # is read from the image inspect below — not hardcoded.
    task_json_str = _json.dumps(task_payload)
    escaped = task_json_str.replace("\\", "\\\\").replace("'", "'\\''")
    config["Cmd"] = []
    config["OpenStdin"] = False
    config["Tty"] = False

    # Merge user-provided secrets into container env vars (override defaults).
    if user_secrets:
        existing_env = config.get("Env", [])
        for k, v in user_secrets.items():
            existing_env.append(f"{k}={v}")
        config["Env"] = existing_env

    docker = _aiodocker.Docker()
    try:
        try:
            image_info = await docker.images.inspect(config["Image"])
        except _aiodocker.exceptions.DockerError as exc:
            if exc.status == 404:
                raise ImageNotBuiltError(
                    f"Image '{config['Image']}' not found — build the dockerfile first."
                ) from exc
            raise

        # Read the image's ENTRYPOINT to know what to pipe into.
        image_ep = (image_info.get("Config") or {}).get("Entrypoint") or []
        if isinstance(image_ep, list) and image_ep:
            ep_cmd = " ".join(image_ep)
        elif isinstance(image_ep, str) and image_ep:
            ep_cmd = image_ep
        else:
            ep_cmd = "/entrypoint.sh"

        config["Entrypoint"] = [
            "sh",
            "-c",
            f"printf '%s\\n' '{escaped}' | {ep_cmd}",
        ]

        container = await docker.containers.create(config=config, name=name)
        try:
            await container.start()

            # Notify the caller with the Docker container ID + name.
            if on_container_started is not None:
                inspect = await container.show()
                cid = inspect.get("Id", "")
                cname = (inspect.get("Name") or "").lstrip("/")
                await on_container_started(cid, cname)

            # Stream stdout + stderr — the entrypoint emits newline-delimited
            # JSON on stdout; stderr carries diagnostics (e.g. "command not
            # found") that we relay as raw events.
            buffer = b""
            try:
                async for line in container.log(
                    stdout=True, stderr=True, follow=True
                ):
                    if isinstance(line, bytes):
                        buffer += line
                    else:
                        buffer += line.encode("utf-8")
                    while b"\n" in buffer:
                        chunk, buffer = buffer.split(b"\n", 1)
                        text = chunk.decode("utf-8", errors="replace").strip()
                        if not text:
                            continue
                        try:
                            yield _json.loads(text)
                        except _json.JSONDecodeError:
                            yield {"type": "raw", "data": text}
                if buffer:
                    text = buffer.decode("utf-8", errors="replace").strip()
                    if text:
                        try:
                            yield _json.loads(text)
                        except _json.JSONDecodeError:
                            yield {"type": "raw", "data": text}
            except _asyncio.CancelledError:
                raise

            try:
                await _asyncio.wait_for(
                    container.wait(), timeout=max(1, timeout_seconds)
                )
            except _asyncio.TimeoutError:
                yield {"type": "error", "message": "Timeout"}
            inspect = await container.show()
            state = inspect.get("State") or {}
            exit_code = int(state.get("ExitCode", 0) or 0)
            yield {
                "type": "done",
                "status": "success" if exit_code == 0 else "failure",
                "exit_code": exit_code,
            }
        finally:
            try:
                await container.delete(force=True)
            except Exception:
                pass
    finally:
        await docker.close()


async def stop(container_id: str) -> None:
    """Stop and remove a container by its Docker id."""
    docker = aiodocker.Docker()
    try:
        try:
            container = docker.containers.container(container_id=container_id)
            # Confirm it is agflow-managed before touching it.
            inspect = await container.show()
        except aiodocker.exceptions.DockerError as exc:
            if exc.status == 404:
                raise ContainerNotFoundError(
                    f"Container '{container_id}' not found"
                ) from exc
            raise

        labels = (inspect.get("Config") or {}).get("Labels") or {}
        if labels.get(_AGFLOW_MANAGED_LABEL) != "true":
            raise ContainerNotFoundError(
                f"Container '{container_id}' is not managed by agflow"
            )

        try:
            await container.stop(timeout=10)
        except aiodocker.exceptions.DockerError:
            # Already stopped or in a weird state — still try to remove.
            pass
        await container.delete(force=True)
        _log.info("container.stop", container_id=container_id)
    finally:
        await docker.close()
