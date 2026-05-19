"""PITR basebackup service — ensure_stanza initialization.

Other operations (list/get/trigger/delete/push/prune) come in later tasks
(T9, T10) to keep this file under 300 lines per CLAUDE.md.
"""
from __future__ import annotations

import json

import structlog

from agflow.docker.exec_helper import docker_exec

log = structlog.get_logger(__name__)

POSTGRES_CONTAINER = "agflow-postgres"
STANZA = "agflow"


async def _pg_exec(args: list[str]) -> tuple[int, str, str]:
    """Run `pgbackrest <args>` inside the agflow-postgres container."""
    return await docker_exec(POSTGRES_CONTAINER, ["pgbackrest", *args])


async def ensure_stanza() -> None:
    """Idempotent stanza initialization.

    Called from `main.py` lifespan at backend startup. If the stanza already
    exists (per `pgbackrest info --output=json`), no-op. Otherwise create it.
    Raises RuntimeError if creation fails.
    """
    code, stdout, _ = await _pg_exec(["--stanza=" + STANZA, "info", "--output=json"])
    if code == 0 and stdout.strip():
        try:
            info = json.loads(stdout)
            if isinstance(info, list) and any(s.get("name") == STANZA for s in info):
                log.info("pitr.stanza.already_exists", stanza=STANZA)
                return
        except json.JSONDecodeError:
            log.warning("pitr.stanza.info_unparseable", stdout=stdout[:200])

    log.info("pitr.stanza.creating", stanza=STANZA)
    code, _, err = await _pg_exec(["--stanza=" + STANZA, "stanza-create"])
    if code != 0:
        raise RuntimeError(f"pgbackrest stanza-create failed: {err}")
    log.info("pitr.stanza.created", stanza=STANZA)
