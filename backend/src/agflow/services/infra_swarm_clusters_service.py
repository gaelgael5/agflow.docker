"""Infra swarm clusters service — CRUD + tokens Fernet.

Tokens Worker/Manager sont chiffres au repos via crypto_service (Fernet).
Decrypt uniquement en memoire au moment d'un swarm_join.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.services import crypto_service

_log = structlog.get_logger(__name__)

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


# ── Tokens helpers (purs, testables sans DB) ─────────────────────────────


def encrypt_tokens(*, worker: str, manager: str) -> dict[str, str]:
    """Encrypt worker + manager tokens via Fernet. Returns dict with the 2 ciphertexts."""
    return {
        "worker_encrypted": crypto_service.encrypt(worker) or "",
        "manager_encrypted": crypto_service.encrypt(manager) or "",
    }


def decrypt_tokens(*, worker_encrypted: str, manager_encrypted: str) -> dict[str, str]:
    """Decrypt tokens. Returns clear-text tokens. NEVER persist or log results."""
    return {
        "worker": crypto_service.decrypt(worker_encrypted) or "",
        "manager": crypto_service.decrypt(manager_encrypted) or "",
    }


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
    """Internal-only : returns cluster row + ENCRYPTED tokens.

    Used by swarm_join orchestration. Caller is responsible for decryption
    via decrypt_tokens() and must NOT persist or log the clear values.
    """
    return await fetch_one(
        """
        SELECT id, name, manager_addr,
               join_token_worker_encrypted, join_token_manager_encrypted,
               created_at, updated_at
        FROM infra_swarm_clusters WHERE id = $1
        """,
        cluster_id,
    )


async def create(
    *,
    name: str,
    manager_addr: str,
    join_token_worker: str,
    join_token_manager: str,
) -> dict[str, Any]:
    """Create a cluster. Tokens are encrypted Fernet before storage."""
    enc = encrypt_tokens(worker=join_token_worker, manager=join_token_manager)
    row = await fetch_one(
        """
        INSERT INTO infra_swarm_clusters
            (name, manager_addr, join_token_worker_encrypted, join_token_manager_encrypted)
        VALUES ($1, $2, $3, $4)
        RETURNING id, name, manager_addr, created_at, updated_at
        """,
        name, manager_addr, enc["worker_encrypted"], enc["manager_encrypted"],
    )
    _log.info("swarm_cluster.created", cluster_id=str(row["id"]) if row else None, name=name)
    assert row is not None  # RETURNING garanti
    return dict(row)


async def delete(cluster_id: UUID) -> None:
    """Delete a cluster. FK ON DELETE SET NULL on infra_machines."""
    await execute("DELETE FROM infra_swarm_clusters WHERE id = $1", cluster_id)
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
