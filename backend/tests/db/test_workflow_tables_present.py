"""Vérifie que les tables et colonnes du contrat workflow sont en place.

Le schéma a été livré via 001_init.sql consolidé. Ce test fait office
de garde-fou pour détecter une régression de structure avant qu'elle
ne casse les services en T2-T8.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from asyncpg import Connection

from agflow.db.pool import get_pool
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def _column_exists(conn: Connection, table: str, column: str) -> bool:
    row = await conn.fetchrow(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = $1 AND column_name = $2
        """,
        table,
        column,
    )
    return row is not None


async def _table_exists(conn: Connection, table: str) -> bool:
    row = await conn.fetchrow(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_name = $1
        """,
        table,
    )
    return row is not None


async def test_workflow_tables_exist(fresh_db: Connection):
    """Tables nouvelles requises par le contrat workflow."""
    for t in ("hmac_keys", "tasks", "outbound_hooks"):
        assert await _table_exists(fresh_db, t), f"table manquante : {t}"


async def test_sessions_workflow_columns(fresh_db: Connection):
    """Sessions étendues : callback_url, callback_hmac_key_id, project_runtime_id."""
    for c in ("callback_url", "callback_hmac_key_id", "project_runtime_id"):
        assert await _column_exists(fresh_db, "sessions", c), (
            f"colonne sessions.{c} manquante"
        )


async def test_agents_instances_mcp_bindings_injected(fresh_db: Connection):
    assert await _column_exists(
        fresh_db, "agents_instances", "mcp_bindings_injected"
    ), "colonne agents_instances.mcp_bindings_injected manquante"


async def test_instances_provisioning_columns(fresh_db: Connection):
    """Resources étendues : connection_params, mcp_bindings, setup_steps, provisioning_status."""
    for c in (
        "connection_params",
        "mcp_bindings",
        "setup_steps",
        "provisioning_status",
    ):
        assert await _column_exists(fresh_db, "instances", c), (
            f"colonne instances.{c} manquante"
        )
