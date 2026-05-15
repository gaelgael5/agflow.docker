"""Infra swarm clusters service — CRUD + tokens via Harpocrate.

Les tokens worker/manager sont stockés dans Harpocrate ; les colonnes DB
`join_token_worker_encrypted` / `join_token_manager_encrypted` conservent
un vault ref (`${vault://HARPOCRATE_KEY:swarm_clusters/<id>/<role>}`).

Le déchiffrement n'a lieu qu'en mémoire dans `get_with_tokens()`, appelée
uniquement par l'orchestration swarm_join. NE JAMAIS persister ni logger
les valeurs claires.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.services import vault_client

_log = structlog.get_logger(__name__)

_VAULT_REF_RE = re.compile(r"^\$\{vault://([^:]+):(.+)\}$")
_VAULT_KEY_NAME = "HARPOCRATE_KEY"


def _vault_path_worker(cluster_id: UUID) -> str:
    return f"swarm_clusters/{cluster_id}/worker"


def _vault_path_manager(cluster_id: UUID) -> str:
    return f"swarm_clusters/{cluster_id}/manager"


def _vault_ref(path: str) -> str:
    return f"${{vault://{_VAULT_KEY_NAME}:{path}}}"


def _parse_vault_ref(value: str | None) -> str | None:
    """Retourne le chemin vault si value est un vault ref valide, sinon None."""
    if not value:
        return None
    m = _VAULT_REF_RE.match(value)
    return m.group(2) if (m and m.group(1) == _VAULT_KEY_NAME) else None


_LIST_SQL = """
    SELECT
        c.id, c.name, c.manager_addr, c.created_at, c.updated_at,
        COUNT(m.id) FILTER (WHERE m.swarm_cluster_id IS NOT NULL) AS node_count,
        COUNT(m.id) FILTER (WHERE m.swarm_node_role = 'manager')  AS manager_count,
        COUNT(m.id) FILTER (WHERE m.swarm_node_role = 'worker')   AS worker_count
    FROM infra_swarm_clusters c
    LEFT JOIN infra_machines m ON m.swarm_cluster_id = c.id
    GROUP BY c.id
    ORDER BY c.name
"""


# ── CRUD (DB-bound, integration tested via endpoints) ────────────────────


async def list_all() -> list[dict[str, Any]]:
    """List all clusters with node counts. Tokens NEVER returned."""
    rows = await fetch_all(_LIST_SQL)
    return [dict(r) for r in rows]


async def get_by_id(cluster_id: UUID) -> dict[str, Any] | None:
    """Get one cluster by id. Tokens NEVER returned."""
    row = await fetch_one(
        _LIST_SQL.replace("ORDER BY c.name", "HAVING c.id = $1 ORDER BY c.name"),
        cluster_id,
    )
    return dict(row) if row else None


async def get_with_tokens(cluster_id: UUID) -> dict[str, Any] | None:
    """Internal-only : returns cluster row + CLEAR tokens (fetched from vault).

    Utilisé par swarm_actions_service.join_cluster. NE JAMAIS persister ni
    logger les valeurs `join_token_worker` / `join_token_manager`.
    """
    row = await fetch_one(
        """
        SELECT id, name, manager_addr,
               join_token_worker_encrypted, join_token_manager_encrypted,
               created_at, updated_at
        FROM infra_swarm_clusters WHERE id = $1
        """,
        cluster_id,
    )
    if row is None:
        return None

    worker_path = _parse_vault_ref(row["join_token_worker_encrypted"])
    manager_path = _parse_vault_ref(row["join_token_manager_encrypted"])

    worker_clear = await vault_client.get_secret(worker_path) if worker_path else ""
    manager_clear = await vault_client.get_secret(manager_path) if manager_path else ""

    return {
        "id": row["id"],
        "name": row["name"],
        "manager_addr": row["manager_addr"],
        "join_token_worker": worker_clear,
        "join_token_manager": manager_clear,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def create(
    *,
    name: str,
    manager_addr: str,
    join_token_worker: str,
    join_token_manager: str,
) -> dict[str, Any]:
    """Create a cluster. Tokens sont poussés dans Harpocrate ; la DB stocke un ref."""
    # 1. INSERT row sans tokens, RETURNING id pour stabiliser le path vault.
    row = await fetch_one(
        """
        INSERT INTO infra_swarm_clusters (name, manager_addr)
        VALUES ($1, $2)
        RETURNING id, name, manager_addr, created_at, updated_at
        """,
        name, manager_addr,
    )
    assert row is not None
    cluster_id: UUID = row["id"]

    # 2. Push secrets puis UPDATE row avec les refs.
    created_paths: list[str] = []
    try:
        worker_path = _vault_path_worker(cluster_id)
        await vault_client.create_secret(worker_path, join_token_worker)
        created_paths.append(worker_path)

        manager_path = _vault_path_manager(cluster_id)
        await vault_client.create_secret(manager_path, join_token_manager)
        created_paths.append(manager_path)

        await execute(
            """
            UPDATE infra_swarm_clusters
               SET join_token_worker_encrypted = $2,
                   join_token_manager_encrypted = $3
             WHERE id = $1
            """,
            cluster_id, _vault_ref(worker_path), _vault_ref(manager_path),
        )
    except Exception:
        for path in created_paths:
            try:
                await vault_client.delete_secret(path)
            except Exception:
                _log.warning("swarm_cluster.vault_rollback_failed", path=path)
        await execute("DELETE FROM infra_swarm_clusters WHERE id = $1", cluster_id)
        raise

    _log.info("swarm_cluster.created", cluster_id=str(cluster_id), name=name)
    return dict(row)


async def delete(cluster_id: UUID) -> None:
    """Delete a cluster + supprime les secrets vault. FK ON DELETE SET NULL sur machines."""
    existing = await fetch_one(
        """
        SELECT join_token_worker_encrypted, join_token_manager_encrypted
        FROM infra_swarm_clusters WHERE id = $1
        """,
        cluster_id,
    )

    await execute("DELETE FROM infra_swarm_clusters WHERE id = $1", cluster_id)

    if existing is not None:
        paths = [
            p for p in (
                _parse_vault_ref(existing["join_token_worker_encrypted"]),
                _parse_vault_ref(existing["join_token_manager_encrypted"]),
            )
            if p
        ]
        for path in paths:
            try:
                await vault_client.delete_secret(path)
            except Exception:
                _log.warning(
                    "swarm_cluster.vault_delete_failed",
                    cluster_id=str(cluster_id), path=path,
                )

    _log.info("swarm_cluster.deleted", cluster_id=str(cluster_id))


async def is_last_node(cluster_id: UUID, exclude_machine_id: UUID) -> bool:
    """Returns True if `cluster_id` has 0 nodes besides `exclude_machine_id`."""
    row = await fetch_one(
        """
        SELECT COUNT(*) AS cnt FROM infra_machines
        WHERE swarm_cluster_id = $1 AND id != $2
        """,
        cluster_id, exclude_machine_id,
    )
    return (row["cnt"] if row else 0) == 0
