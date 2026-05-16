"""Infra swarm clusters service — CRUD + tokens via Harpocrate.

Les tokens worker/manager sont stockés dans Harpocrate ; les colonnes DB
`join_token_worker_encrypted` / `join_token_manager_encrypted` conservent
un vault ref portant le nom logique du coffre cible :

    ${vault://<vault_name>:swarm_clusters/<id>/<role>}

Le déchiffrement n'a lieu qu'en mémoire dans `get_with_tokens()`, appelée
uniquement par l'orchestration swarm_join. NE JAMAIS persister ni logger
les valeurs claires.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.services import harpocrate_vaults_service, vault_client

_log = structlog.get_logger(__name__)


def _path_worker(cluster_id: UUID) -> str:
    return f"swarm_clusters/{cluster_id}/worker"


def _path_manager(cluster_id: UUID) -> str:
    return f"swarm_clusters/{cluster_id}/manager"


async def _require_default_vault_name() -> str:
    """Résout le nom du coffre Harpocrate par défaut. Lève si aucun configuré."""
    default = await harpocrate_vaults_service.get_default()
    if default is None:
        raise vault_client.VaultNotFoundError(
            "No default Harpocrate vault configured — see /settings"
        )
    return default.name


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

    async def _read(ref: str | None) -> str:
        if ref is None or vault_client.parse_ref(ref) is None:
            return ""
        return await vault_client.resolve_ref(ref)

    return {
        "id": row["id"],
        "name": row["name"],
        "manager_addr": row["manager_addr"],
        "join_token_worker": await _read(row["join_token_worker_encrypted"]),
        "join_token_manager": await _read(row["join_token_manager_encrypted"]),
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
    """Create a cluster. Tokens sont poussés dans Harpocrate ; la DB stocke un ref.

    Les colonnes `join_token_*_encrypted` sont NOT NULL (cf. migration 087) :
    on génère l'id en Python, on push les secrets puis on fait un seul INSERT.
    """
    vault_name = await _require_default_vault_name()
    cluster_id = uuid4()
    created_paths: list[str] = []
    try:
        worker_path = _path_worker(cluster_id)
        await vault_client.create_secret(worker_path, join_token_worker, vault_name=vault_name)
        created_paths.append(worker_path)

        manager_path = _path_manager(cluster_id)
        await vault_client.create_secret(manager_path, join_token_manager, vault_name=vault_name)
        created_paths.append(manager_path)

        row = await fetch_one(
            """
            INSERT INTO infra_swarm_clusters
                (id, name, manager_addr,
                 join_token_worker_encrypted, join_token_manager_encrypted)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, name, manager_addr, created_at, updated_at
            """,
            cluster_id, name, manager_addr,
            vault_client.build_ref(vault_name, worker_path),
            vault_client.build_ref(vault_name, manager_path),
        )
        assert row is not None
    except Exception:
        for path in created_paths:
            try:
                await vault_client.delete_secret(path, vault_name=vault_name)
            except Exception:
                _log.warning("swarm_cluster.vault_rollback_failed", path=path)
        raise

    _log.info("swarm_cluster.created", cluster_id=str(cluster_id), name=name, vault=vault_name)
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
        refs_to_purge: list[tuple[str, str]] = []  # (vault_name, path)
        for raw in (
            existing["join_token_worker_encrypted"],
            existing["join_token_manager_encrypted"],
        ):
            parsed = vault_client.parse_ref(raw)
            if parsed is not None:
                refs_to_purge.append(parsed)

        for vname, path in refs_to_purge:
            try:
                await vault_client.delete_secret(path, vault_name=vname)
            except Exception:
                _log.warning(
                    "swarm_cluster.vault_delete_failed",
                    cluster_id=str(cluster_id), vault=vname, path=path,
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
