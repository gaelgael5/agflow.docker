"""Swarm actions service : init/join/leave orchestration.

Chaque action :
  1. Charge la machine cible (DB)
  2. Verifie les preconditions (swarm_ready, membership exclusivite)
  3. Lance le script ops via ssh_executor
  4. Parse le JSON de retour
  5. Persiste en DB (swarm_clusters + machines)
  6. Trace dans infra_machines_runs

Si l'une des etapes echoue, leve SwarmActionError (capture par le router HTTP).
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_one
from agflow.services import (
    infra_certificates_service,
    infra_swarm_clusters_service,
    ssh_executor,
)

_log = structlog.get_logger(__name__)


class SwarmActionError(Exception):
    """Raised when a swarm_init/join/leave action fails on preconditions or script."""


# ── Helpers prives (overridable via patch dans les tests) ────────────────


async def _get_machine(machine_id: UUID) -> dict[str, Any] | None:
    return await fetch_one(
        """
        SELECT id, host, port, username, certificate_id, swarm_ready,
               swarm_mode, swarm_cluster_id, swarm_node_role
        FROM infra_machines WHERE id = $1
        """,
        machine_id,
    )


async def _exec_swarm_script(
    machine: dict[str, Any], script_args: list[str]
) -> dict[str, Any]:
    """Run init-swarm-node.sh via ssh on the target machine, parse JSON output."""
    private_key = None
    passphrase = None
    if machine.get("certificate_id"):
        cert = await infra_certificates_service.get_decrypted(machine["certificate_id"])
        if cert:
            private_key = cert.get("private_key")
            passphrase = cert.get("passphrase")

    cmd = "init-swarm-node.sh " + " ".join(script_args)
    result = await ssh_executor.exec_command(
        host=machine["host"],
        port=machine["port"],
        username=machine["username"],
        password=None,
        private_key=private_key,
        passphrase=passphrase,
        command=cmd,
    )
    if result["exit_code"] != 0:
        raise SwarmActionError(
            f"Script failed (exit_code={result['exit_code']}): {result['stderr'][:200]}"
        )
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        raise SwarmActionError(f"Script output is not valid JSON: {exc}") from exc


async def _persist_init_result(
    *, machine_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Insert cluster + link machine. Returns the created cluster row (no tokens)."""
    swarm_block = payload["swarm"]
    cluster = await infra_swarm_clusters_service.create(
        name=swarm_block["cluster_name"],
        manager_addr=swarm_block["manager_addr"],
        join_token_worker=swarm_block["join_token_worker"],
        join_token_manager=swarm_block["join_token_manager"],
    )
    await execute(
        """
        UPDATE infra_machines SET
            swarm_cluster_id = $1,
            swarm_node_role = 'manager',
            swarm_mode = 'active'
        WHERE id = $2
        """,
        cluster["id"], machine_id,
    )
    return cluster


# ── Public API ───────────────────────────────────────────────────────────


async def init_cluster(*, machine_id: UUID, cluster_name: str) -> dict[str, Any]:
    """Initialise un nouveau cluster Swarm sur la machine cible.

    Preconditions :
    - machine.swarm_ready = TRUE
    - machine.swarm_cluster_id IS NULL (pas deja membre)

    Levée SwarmActionError sur violation de precondition ou echec script.
    Retourne le row du cluster cree (sans tokens).
    """
    machine = await _get_machine(machine_id)
    if machine is None:
        raise SwarmActionError(f"Machine {machine_id} not found")
    if machine.get("swarm_cluster_id") is not None:
        raise SwarmActionError(f"Machine {machine_id} is already member of a cluster")
    if not machine.get("swarm_ready"):
        raise SwarmActionError(f"Machine {machine_id} is not swarm-ready")

    payload = await _exec_swarm_script(machine, ["--init", "--name", cluster_name])
    if payload.get("status") != "ok":
        raise SwarmActionError(
            f"Script returned partial status (exit_code={payload.get('exit_code')})"
        )

    cluster = await _persist_init_result(machine_id=machine_id, payload=payload)
    _log.info("swarm.init", machine_id=str(machine_id), cluster_id=str(cluster["id"]))
    return cluster


async def join_cluster(
    *, machine_id: UUID, cluster_id: UUID, role: str
) -> dict[str, Any]:
    """Joint la machine au cluster existant en role 'manager' ou 'worker'.

    Preconditions : machine.swarm_ready, pas deja membre, cluster existe.
    Token deciphere uniquement en memoire pour le passer au script ops.
    """
    if role not in ("manager", "worker"):
        raise SwarmActionError(f"Invalid role '{role}' (expected manager|worker)")

    machine = await _get_machine(machine_id)
    if machine is None:
        raise SwarmActionError(f"Machine {machine_id} not found")
    if machine.get("swarm_cluster_id") is not None:
        raise SwarmActionError(f"Machine {machine_id} is already member of a cluster")
    if not machine.get("swarm_ready"):
        raise SwarmActionError(f"Machine {machine_id} is not swarm-ready")

    cluster = await infra_swarm_clusters_service.get_with_tokens(cluster_id)
    if cluster is None:
        raise SwarmActionError(f"Cluster {cluster_id} not found")

    # get_with_tokens() fetch les tokens en clair depuis Harpocrate.
    # Les valeurs ne doivent JAMAIS être persistées ni loggées.
    token = cluster["join_token_manager"] if role == "manager" else cluster["join_token_worker"]

    args = ["--join", "--manager", str(cluster["manager_addr"]), "--token", token]
    if role == "manager":
        args.append("--manager-role")
    payload = await _exec_swarm_script(machine, args)
    if payload.get("status") != "ok":
        raise SwarmActionError(
            f"Script returned partial status (exit_code={payload.get('exit_code')})"
        )

    await execute(
        """
        UPDATE infra_machines SET
            swarm_cluster_id = $1,
            swarm_node_role = $2,
            swarm_mode = 'active'
        WHERE id = $3
        """,
        cluster_id, role, machine_id,
    )
    _log.info("swarm.join", machine_id=str(machine_id), cluster_id=str(cluster_id), role=role)
    return {
        "joined": payload["swarm"].get("joined", True),
        "node_id": payload["swarm"].get("node_id"),
        "role": role,
    }


async def leave_cluster(*, machine_id: UUID, force: bool = False) -> dict[str, Any]:
    """Retire la machine de son cluster. Drop le cluster si dernier node."""
    machine = await _get_machine(machine_id)
    if machine is None:
        raise SwarmActionError(f"Machine {machine_id} not found")
    if machine.get("swarm_cluster_id") is None:
        raise SwarmActionError(f"Machine {machine_id} is not part of any cluster")

    cluster_id_was = machine["swarm_cluster_id"]

    args = ["--leave"] + (["--force"] if force else [])
    payload = await _exec_swarm_script(machine, args)
    if payload.get("status") != "ok":
        raise SwarmActionError(
            f"Script returned partial status (exit_code={payload.get('exit_code')})"
        )

    await execute(
        """
        UPDATE infra_machines SET
            swarm_cluster_id = NULL,
            swarm_node_role = NULL,
            swarm_mode = 'inactive'
        WHERE id = $1
        """,
        machine_id,
    )

    cluster_dropped = False
    if await infra_swarm_clusters_service.is_last_node(cluster_id_was, machine_id):
        await infra_swarm_clusters_service.delete(cluster_id_was)
        cluster_dropped = True

    _log.info("swarm.leave", machine_id=str(machine_id), cluster_dropped=cluster_dropped)
    return {"left": True, "cluster_dropped": cluster_dropped}
