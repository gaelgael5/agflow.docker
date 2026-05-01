"""Build the SSH step list to deploy or remove a Swarm stack.

Deployment used to be a `docker compose up -d` on the target machine; we now
push the rendered compose as a Swarm `stack.yml` and run
`docker stack deploy -c stack.yml <STACK_NAME>` instead.

The helpers here produce the ordered list of `(step_name, command, stdin)`
tuples consumed by `ssh_executor.exec_command` — keeping the SSH plumbing in
the route handlers and the deployment command shape in one tested place.
"""
from __future__ import annotations

import re

# Docker Swarm stack names accept lowercase alphanum + `_` and `-`. Other
# characters are normalized to `_`. Docker enforces a max length of 63 chars.
_STACK_NAME_INVALID = re.compile(r"[^a-z0-9_-]+")
_STACK_NAME_MAX_LEN = 63


def slug_stack_name(value: str) -> str:
    """Normalize an arbitrary string into a valid Docker Swarm stack name.

    Lowercases, replaces invalid chars with `_`, collapses runs of separators,
    strips leading/trailing separators, and truncates to 63 chars. Raises
    ValueError if the input becomes empty after normalization.
    """
    s = value.lower()
    s = _STACK_NAME_INVALID.sub("_", s)
    # Collapse runs of `_` or `-` into a single separator (preserve which one
    # appeared first in each run).
    s = re.sub(r"([_-])[_-]+", r"\1", s)
    s = s.strip("_-")
    if not s:
        raise ValueError(
            f"Cannot derive a Swarm stack name from {value!r}: empty after normalization"
        )
    return s[:_STACK_NAME_MAX_LEN]


def build_deploy_steps(
    *,
    remote_dir: str,
    compose_content: str,
    env_content: str,
    stack_name: str,
    extra_steps_before_deploy: list[tuple[str, str, str | None]] | None = None,
) -> list[tuple[str, str, str | None]]:
    """Build the SSH step list for a `docker stack deploy`.

    Steps:
      1. mkdir -p <remote_dir>
      2. write stack.yml
      3. write .env
      4. (optional) extra steps such as registry login
      5. source .env then docker stack deploy -c stack.yml <stack_name>

    `--resolve-image=never` is passed so Docker uses the image tag as written
    in the compose without an extra registry round-trip — registry pulls go
    through the explicit login step instead.
    """
    safe_name = slug_stack_name(stack_name)
    deploy_cmd = (
        "set -a; "
        f". {remote_dir}/.env; "
        "set +a; "
        f"docker stack deploy --resolve-image=never "
        f"-c {remote_dir}/stack.yml {safe_name}"
    )
    steps: list[tuple[str, str, str | None]] = [
        ("mkdir", f"mkdir -p {remote_dir}", None),
        ("write_stack", f"cat > {remote_dir}/stack.yml", compose_content),
        ("write_env", f"cat > {remote_dir}/.env", env_content),
    ]
    if extra_steps_before_deploy:
        steps.extend(extra_steps_before_deploy)
    steps.append(("stack_deploy", deploy_cmd, None))
    return steps


def build_rm_steps(stack_name: str) -> list[tuple[str, str, str | None]]:
    """Build the SSH step list to remove a Swarm stack."""
    safe_name = slug_stack_name(stack_name)
    return [("stack_rm", f"docker stack rm {safe_name}", None)]
